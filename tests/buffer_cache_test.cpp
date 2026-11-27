#include "buffer_cache.h"
#include <cassert>
#include <memory>
#include <unordered_map>

struct Buffer {
    int cache_stamp;
    bool busy;
};

int main() {
    waydroid_manager::BufferReleaseState state;
    assert(!state.in_use());
    assert(state.next_point() == 1);
    state.submit();
    state.submit();
    assert(state.in_use());
    assert(state.current_point() == 2);
    assert(state.release() == 2);
    assert(!state.in_use());
    assert(state.release() == 0);
    state.submit();
    assert(state.release() == 1);

    std::unordered_map<int, std::unique_ptr<Buffer>> buffers;
    buffers.emplace(1, std::make_unique<Buffer>(Buffer{4, false}));
    buffers.emplace(2, std::make_unique<Buffer>(Buffer{1, true}));
    buffers.emplace(3, std::make_unique<Buffer>(Buffer{2, false}));
    buffers.emplace(4, std::make_unique<Buffer>(Buffer{3, false}));
    auto eligible = [](const Buffer& buffer) { return !buffer.busy; };
    waydroid_manager::trim_buffer_cache(buffers, 2, eligible);
    assert(buffers.count(1) == 1);
    assert(buffers.count(2) == 1);
    assert(buffers.count(3) == 0);
    assert(buffers.count(4) == 0);
    waydroid_manager::trim_buffer_cache(buffers, 0, eligible);
    assert(buffers.size() == 1 && buffers.count(2));
    buffers.at(2)->busy = false;
    waydroid_manager::trim_buffer_cache(buffers, 0, eligible);
    assert(buffers.empty());
}
