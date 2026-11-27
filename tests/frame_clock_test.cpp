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

    const int64_t refresh = 1000000000LL / 120;
    assert(waydroid_manager::is_refresh_multiple(1000000000LL / 40, refresh));
    assert(waydroid_manager::is_refresh_multiple(1000000000LL / 12, refresh));
    assert(!waydroid_manager::is_refresh_multiple(1000000000LL / 14, refresh));
    assert(!waydroid_manager::is_refresh_multiple(refresh, 0));

    FrameClock arbitrary;
    const int64_t period = 1000000000LL / 47;
    assert(arbitrary.deadline(0, period) == period);
    assert(arbitrary.consume(period - 1) == 0);
    assert(arbitrary.consume(period * 5 + 12345) == period * 5);
    assert(arbitrary.deadline(period * 5 + 12345, period) == period * 6);
    assert(arbitrary.deadline(period * 6, 25000000) == period * 6 + 25000000);

    // Estimate the display period from presentations, including missed frames.
    waydroid_manager::RefreshEstimator refresh;
    const int64_t reported = 1000000000LL / 120;
    const int64_t measured = reported - 4000;
    int64_t time = 1000000000LL;
    assert(refresh.observe(time, reported) == 0);
    for (int i = 0; i < 130; ++i) {
        time += measured * (i % 20 == 0 ? 2 : 1);
        refresh.observe(time, reported);
    }
    assert(refresh.observe(time, reported) == measured);
    assert(refresh.observe(time + 10000000000LL, reported) == measured);
    assert(refresh.observe(time + 11000000000LL, 1000000000LL / 60) == 0);

    FrameClock adjusted;
    const auto initial = adjusted.deadline(time, reported);
    assert(adjusted.deadline(time, measured) == initial);
    assert(adjusted.consume(initial) == initial);
    assert(adjusted.deadline(initial, measured) == initial + measured);
    FrameClock late;
    const int64_t late_period = 1000000;
    const int64_t late_deadline = late.deadline(time, late_period);
    const int64_t late_presented = late_deadline + late_period * 9 / 10;
    late.align(late_presented, late_presented);
    assert(late.deadline(late_presented, late_period) == late_deadline - late_period / 16);

    // A nominal 120 Hz panel runs slightly slow and starts half a cycle out of phase.
    FrameClock locked;
    const int64_t nominal = 1000000000LL / 120;
    const int64_t host = nominal + 1000;
    const int64_t origin = 1000000000LL;
    int64_t now = origin + nominal / 2;
    int64_t previous = now;
    for (int i = 0; i < 2000; ++i) {
        auto next = locked.deadline(now, nominal);
        auto latest = origin + ((now - origin) / host) * host;
        locked.align(now, latest);
        next = locked.deadline(now, nominal);
        locked.align(now, latest);  // duplicate feedback from the same commit
        locked.align(now, now + host);
        locked.align(now, now - 3 * host);
        assert(locked.deadline(now, nominal) == next);
        assert(next - previous >= nominal - nominal / 16);
        assert(next - previous <= nominal + nominal / 16);
        if (i > 16) {
            int64_t phase = (next - origin) % host;
            assert(std::min(phase, host - phase) <= host - nominal);
        }
        now = next + 10000;
        assert(locked.consume(now) == next);
        previous = next;
    }
}
