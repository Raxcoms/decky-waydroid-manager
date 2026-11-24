#pragma once

#include <algorithm>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>

namespace waydroid_manager {

class BufferBacking {
public:
    BufferBacking() = default;
    BufferBacking(const BufferBacking&) = delete;
    BufferBacking& operator=(const BufferBacking&) = delete;

    ~BufferBacking() {
        for (const auto& file : files_)
            close(file.fd);
    }

    void capture(const int* data, int fd_count, int int_count) {
        if (fd_count <= 0 || int_count < 0)
            return;
        for (int i = 0; i < fd_count; ++i) {
            int fd = fcntl(data[i], F_DUPFD_CLOEXEC, 0);
            if (fd < 0)
                return;
            struct stat info;
            if (fstat(fd, &info) != 0 || info.st_ino == 0) {
                close(fd);
                return;
            }
            // Keep the inode alive until its Wayland import is retired.
            files_.push_back({fd, info.st_dev, info.st_ino});
        }
        layout_.assign(data + fd_count, data + fd_count + int_count);
        valid_ = true;
    }

    bool matches(const int* data, int fd_count, int int_count) const {
        if (!valid_ || fd_count != static_cast<int>(files_.size()) ||
                int_count != static_cast<int>(layout_.size()) ||
                !std::equal(layout_.begin(), layout_.end(), data + fd_count))
            return false;
        for (int i = 0; i < fd_count; ++i) {
            struct stat info;
            if (fstat(data[i], &info) != 0 ||
                    info.st_dev != files_[i].device || info.st_ino != files_[i].inode)
                return false;
        }
        return true;
    }

private:
    struct File {
        int fd;
        dev_t device;
        ino_t inode;
    };
    std::vector<File> files_;
    std::vector<int> layout_;
    bool valid_ = false;
};

}
