#define _GNU_SOURCE
#include <errno.h>
#include <dirent.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <sys/mount.h>
#include <linux/mount.h>
#include <linux/openat2.h>
#include <sched.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

static pid_t mapper;

static void fail(const char *operation) {
    perror(operation);
    if (mapper > 0) {
        kill(mapper, SIGKILL);
        waitpid(mapper, NULL, 0);
    }
    exit(EXIT_FAILURE);
}

static uint64_t number(const char *value) {
    char *end;
    errno = 0;
    unsigned long long result = strtoull(value, &end, 10);
    if (errno || !*value || *end || *value == '-') {
        errno = EINVAL;
        fail("Invalid mount identity");
    }
    return result;
}

static void map_file(const char *name, const char *value) {
    char path[80];
    snprintf(path, sizeof(path), "/proc/%ld/%s", (long)mapper, name);
    int fd = open(path, O_WRONLY | O_CLOEXEC);
    if (fd < 0 || write(fd, value, strlen(value)) != (ssize_t)strlen(value))
        fail("Write user namespace mapping");
    close(fd);
}

static int user_namespace(char **values) {
    int ready[2];
    if (pipe2(ready, O_CLOEXEC) < 0)
        fail("Create namespace pipe");
    mapper = fork();
    if (mapper < 0)
        fail("Create user namespace process");
    if (!mapper) {
        close(ready[0]);
        if (unshare(CLONE_NEWUSER) < 0)
            _exit(EXIT_FAILURE);
        if (write(ready[1], "1", 1) != 1)
            _exit(EXIT_FAILURE);
        for (;;)
            pause();
    }
    close(ready[1]);
    char signal;
    if (read(ready[0], &signal, 1) != 1) {
        errno = EIO;
        fail("Initialize user namespace");
    }
    close(ready[0]);
    char mapping[96];
    uint64_t ids[4];
    for (size_t i = 0; i < 4; i++) {
        ids[i] = number(values[i]);
        if (ids[i] >= UINT32_MAX) {
            errno = EINVAL;
            fail("Invalid file owner");
        }
    }
    snprintf(mapping, sizeof(mapping), "%" PRIu64 " %" PRIu64 " 1\n", ids[0], ids[1]);
    map_file("uid_map", mapping);
    map_file("setgroups", "deny");
    snprintf(mapping, sizeof(mapping), "%" PRIu64 " %" PRIu64 " 1\n", ids[2], ids[3]);
    map_file("gid_map", mapping);
    char path[80];
    snprintf(path, sizeof(path), "/proc/%ld/ns/user", (long)mapper);
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0)
        fail("Open user namespace");
    kill(mapper, SIGKILL);
    waitpid(mapper, NULL, 0);
    mapper = 0;
    return fd;
}

static int directory(int root, const char *path) {
    struct open_how how = {.flags = O_PATH | O_DIRECTORY | O_CLOEXEC,
                           .resolve = RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS};
    int fd = syscall(SYS_openat2, root, path + 1, &how, sizeof(how));
    if (fd < 0)
        fail("Open Android shared directory");
    return fd;
}

static uint64_t mount_id(int fd) {
    struct statx info;
    if (statx(fd, "", AT_EMPTY_PATH, STATX_MNT_ID, &info) < 0 || !(info.stx_mask & STATX_MNT_ID))
        fail("Identify shared mount");
    return info.stx_mnt_id;
}

int main(int argc, char **argv) {
    int attach = argc == 10 && !strcmp(argv[1], "mount");
    if (!attach && !(argc == 7 && !strcmp(argv[1], "unmount"))) {
        fputs("Usage: home-mount mount PID NAMESPACE HOME TARGET UID MAP_UID GID MAP_GID\n"
              "       home-mount unmount PID NAMESPACE TARGET MOUNT_ID CREATED_INODE\n", stderr);
        return EXIT_FAILURE;
    }
    uint64_t pid = number(argv[2]);
    if (!pid || pid > INT_MAX)
        return EXIT_FAILURE;
    const char *target = argv[attach ? 5 : 4];
    const char *owned = strstr(target, "/waydroid.manager.storage/files/Host");
    if ((!owned || (owned[strlen("/waydroid.manager.storage/files/Host")] != '\0'
                    && owned[strlen("/waydroid.manager.storage/files/Host")] != '/'))
            || (strncmp(target, "/data/data/", strlen("/data/data/"))
                && strncmp(target, "/data/user/", strlen("/data/user/"))))
        return EXIT_FAILURE;
    char path[64];
    snprintf(path, sizeof(path), "/proc/%" PRIu64, pid);
    int process = open(path, O_PATH | O_DIRECTORY | O_CLOEXEC);
    int ns = openat(process, "ns/mnt", O_RDONLY | O_CLOEXEC);
    int root = openat(process, "root", O_PATH | O_DIRECTORY | O_CLOEXEC);
    struct stat info;
    if (process < 0 || ns < 0 || root < 0 || fstat(ns, &info) < 0 || info.st_ino != number(argv[3])) {
        errno = ESTALE;
        fail("Android mount namespace changed");
    }
    char *parent_path = strdup(target);
    if (!parent_path)
        fail("Allocate shared path");
    char *name = strrchr(parent_path, '/');
    *name++ = '\0';
    int parent = directory(root, parent_path);
    uint64_t created = 0;
    if (attach && mkdirat(parent, name, 0770) == 0) {
        if (fstatat(parent, name, &info, AT_SYMLINK_NOFOLLOW) < 0)
            fail("Identify shared directory");
        created = info.st_ino;
    } else if (attach && errno != EEXIST) {
        fail("Create shared directory");
    }
    int destination = openat(parent, name, O_PATH | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (destination < 0)
        fail("Open shared mount point");
    int tree = -1;
    if (attach) {
        int scan = openat(parent, name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
        DIR *directory = scan < 0 ? NULL : fdopendir(scan);
        if (!directory)
            fail("Read shared mount point");
        struct dirent *entry;
        while ((entry = readdir(directory))) {
            if (strcmp(entry->d_name, ".") && strcmp(entry->d_name, "..")) {
                errno = ENOTEMPTY;
                fail("Shared mount point already contains files");
            }
        }
        closedir(directory);
        int source = open(argv[4], O_PATH | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
        tree = syscall(SYS_open_tree, source, "", AT_EMPTY_PATH | OPEN_TREE_CLONE | OPEN_TREE_CLOEXEC);
        if (source < 0 || tree < 0)
            fail("Clone host home mount");
        int mapping = user_namespace(argv + 6);
        struct mount_attr attributes = {.attr_set = MOUNT_ATTR_IDMAP, .userns_fd = (uint64_t)mapping};
        if (syscall(SYS_mount_setattr, tree, "", AT_EMPTY_PATH, &attributes, sizeof(attributes)) < 0)
            fail("Map shared home ownership");
        close(mapping);
        close(source);
    } else if (mount_id(destination) != number(argv[5])) {
        errno = ESTALE;
        fail("Android shared mount changed");
    }
    // Keep both paths pinned while entering Android's mount namespace.
    if (setns(ns, CLONE_NEWNS) < 0)
        fail("Enter Android mount namespace");
    if (attach) {
        if (syscall(SYS_move_mount, tree, "", destination, "", MOVE_MOUNT_F_EMPTY_PATH | MOVE_MOUNT_T_EMPTY_PATH) < 0)
            fail("Attach shared home");
        printf("%" PRIu64 " %" PRIu64 "\n", mount_id(openat(parent, name, O_PATH | O_DIRECTORY)), created);
    } else {
        if (fchdir(root) < 0 || chroot(".") < 0 || syscall(SYS_umount2, target, MNT_DETACH) < 0)
            fail("Detach shared home");
        created = number(argv[6]);
        if (created && fstatat(parent, name, &info, AT_SYMLINK_NOFOLLOW) == 0 && info.st_ino == created
                && unlinkat(parent, name, AT_REMOVEDIR) < 0)
            fail("Remove shared directory");
    }
    return EXIT_SUCCESS;
}
