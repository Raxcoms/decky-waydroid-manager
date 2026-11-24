#include "buffer_backing.h"
#include <cassert>
#include <cstdio>

int main() {
    auto* first = tmpfile();
    auto* second = tmpfile();
    assert(first && second);
    int handle[] = {fileno(first), fileno(second), 64, 256};
    waydroid_manager::BufferBacking backing;
    backing.capture(handle, 2, 2);
    assert(backing.matches(handle, 2, 2));
    int alias = dup(handle[0]);
    assert(alias >= 0);
    handle[0] = alias;
    assert(backing.matches(handle, 2, 2));
    handle[3] = 128;
    assert(!backing.matches(handle, 2, 2));
    handle[3] = 256;
    int reused_fd = handle[1];
    assert(dup2(alias, reused_fd) == reused_fd);
    assert(!backing.matches(handle, 2, 2));
    assert(!backing.matches(handle, 1, 2));
    close(alias);
    fclose(first);
    fclose(second);
    waydroid_manager::BufferBacking unknown;
    unknown.capture(handle, 0, 2);
    assert(!unknown.matches(handle, 0, 2));
}
