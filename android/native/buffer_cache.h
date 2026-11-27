#pragma once

#include <cstddef>

namespace waydroid_manager {

// Track Wayland ownership even without a software release fence.
class BufferReleaseState {
public:
    unsigned next_point() const { return submitted_ + 1; }
    unsigned current_point() const { return submitted_; }
    void submit() { ++submitted_; }
    bool in_use() const { return submitted_ != released_; }
    unsigned release() {
        unsigned pending = submitted_ - released_;
        released_ = submitted_;
        return pending;
    }

private:
    unsigned submitted_ = 0;
    unsigned released_ = 0;
};

template<class Map, class Eligible>
void trim_buffer_cache(Map& buffers, std::size_t limit, Eligible eligible) {
    while (buffers.size() > limit) {
        auto oldest = buffers.end();
        for (auto it = buffers.begin(); it != buffers.end(); ++it) {
            if (eligible(*it->second) &&
                    (oldest == buffers.end() || it->second->cache_stamp < oldest->second->cache_stamp))
                oldest = it;
        }
        if (oldest == buffers.end())
            return;
        buffers.erase(oldest);
    }
}

}
