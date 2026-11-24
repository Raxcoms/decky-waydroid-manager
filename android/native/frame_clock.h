#pragma once

#include <algorithm>
#include <cstdint>

namespace waydroid_manager {

class FrameClock {
public:
    int64_t deadline(int64_t now, int64_t period) {
        if (period != period_ || next_ == 0) {
            period_ = period;
            next_ = now + period;
        }
        return next_;
    }

    void align(int64_t now, int64_t presented) {
        if (presented <= feedback_ || presented > now || now - presented > 2 * period_)
            return;
        feedback_ = presented;
        // Move toward the nearest scanout phase without skipping or repeating a tick.
        int64_t offset = (next_ - presented) % period_;
        if (offset > period_ / 2)
            offset -= period_;
        const int64_t step = period_ / 16;
        next_ -= std::clamp(offset, -step, step);
    }

    int64_t consume(int64_t now) {
        if (now < next_)
            return 0;
        // Skip missed frames without shifting the cadence to the wake-up time.
        int64_t timestamp = next_ + ((now - next_) / period_) * period_;
        next_ = timestamp + period_;
        return timestamp;
    }

private:
    int64_t period_ = 0;
    int64_t next_ = 0;
    int64_t feedback_ = 0;
};

}
