#pragma once

#include <algorithm>
#include <cstdint>
#include <cstdlib>

namespace waydroid_manager {

class RefreshEstimator {
public:
    int64_t observe(int64_t timestamp, int64_t nominal) {
        if (nominal <= 0)
            return 0;
        if (nominal != nominal_) {
            nominal_ = nominal;
            previous_ = 0;
            elapsed_ = 0;
            frames_ = 0;
            period_ = 0;
        }
        if (timestamp <= previous_)
            return period_;
        if (previous_ == 0) {
            previous_ = timestamp;
            return 0;
        }
        int64_t delta = timestamp - previous_;
        previous_ = timestamp;
        if (delta > 2000000000LL) {
            elapsed_ = 0;
            frames_ = 0;
            return period_;
        }
        int64_t frames = (delta + nominal / 2) / nominal;
        if (frames < 1 || std::abs(delta - frames * nominal) > frames * nominal / 100) {
            elapsed_ = 0;
            frames_ = 0;
            return period_;
        }
        elapsed_ += delta;
        frames_ += frames;
        if (elapsed_ >= 1000000000LL) {
            period_ = elapsed_ / frames_;
            elapsed_ = 0;
            frames_ = 0;
        }
        return period_;
    }

private:
    int64_t nominal_ = 0;
    int64_t previous_ = 0;
    int64_t elapsed_ = 0;
    int64_t frames_ = 0;
    int64_t period_ = 0;
};

class FrameClock {
public:
    int64_t deadline(int64_t now, int64_t period) {
        if (period != period_ || next_ == 0) {
            if (next_ == 0 || std::abs(period - period_) > period_ / 100)
                next_ = now + period;
            period_ = period;
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
        else if (offset < -period_ / 2)
            offset += period_;
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
