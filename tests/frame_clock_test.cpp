#include "frame_clock.h"
#include <algorithm>
#include <cassert>

using waydroid_manager::FrameClock;

int main() {
    // Mixed refresh rates must keep their own cadence over many wake-ups.
    FrameClock primary, external;
    const int64_t primary_period = 1000000000LL / 144;
    const int64_t external_period = 1000000000LL / 60;
    int primary_count = 0, external_count = 0;
    int64_t last_primary = 0, last_external = 0;
    for (int64_t now = 0; now < 10000000000LL;) {
        int64_t next = std::min(primary.deadline(now, primary_period),
                                external.deadline(now, external_period));
        now = next + 10000;
        if (auto timestamp = primary.consume(now)) {
            if (last_primary) assert(timestamp - last_primary == primary_period);
            last_primary = timestamp;
            ++primary_count;
        }
        if (auto timestamp = external.consume(now)) {
            if (last_external) assert(timestamp - last_external == external_period);
            last_external = timestamp;
            ++external_count;
        }
    }
    assert(primary_count == 1440);
    assert(external_count == 600);

    FrameClock arbitrary;
    const int64_t period = 1000000000LL / 47;
    assert(arbitrary.deadline(0, period) == period);
    assert(arbitrary.consume(period - 1) == 0);
    assert(arbitrary.consume(period * 5 + 12345) == period * 5);
    assert(arbitrary.deadline(period * 5 + 12345, period) == period * 6);
    assert(arbitrary.deadline(period * 6, 25000000) == period * 6 + 25000000);
}
