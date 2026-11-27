#include "release_gate.h"
#include <cassert>
#include <chrono>
#include <future>
#include <thread>

using namespace std::chrono_literals;
using waydroid_manager::ReleaseGate;

int main() {
    ReleaseGate gate;
    assert(!gate.snapshot(1));
    gate.submit(1);
    auto first = gate.snapshot(1);
    assert(first);
    assert(!gate.wait({first}, 0ns));
    gate.release(1);
    assert(gate.wait({first}, 0ns));

    // A new use of the same buffer must not extend the old wait.
    gate.submit(1);
    auto second = gate.snapshot(1);
    assert(second.generation != first.generation);
    assert(gate.wait({first}, 0ns));
    assert(!gate.wait({second}, 0ns));

    gate.submit(2);
    auto other = gate.snapshot(2);
    std::promise<void> ready;
    auto started = ready.get_future();
    auto result = std::async(std::launch::async, [&] {
        ready.set_value();
        return gate.wait({second, other}, 2s);
    });
    started.wait();
    gate.release(1);
    assert(!gate.wait({other}, 0ns));
    gate.forget(2);
    assert(result.get());
    assert(!gate.snapshot(2));

    waydroid_manager::ReleaseWait wait;
    using waydroid_manager::ReleaseWaitResult;
    gate.submit(3);
    auto stalled = gate.snapshot(3);
    assert(wait.wait(gate, {stalled}, 0ns) == ReleaseWaitResult::TimedOut);
    gate.submit(4);
    auto next = gate.snapshot(4);
    assert(wait.wait(gate, {next}, 1s) == ReleaseWaitResult::Deferred);
    gate.release(3);
    assert(wait.wait(gate, {next}, 0ns) == ReleaseWaitResult::TimedOut);
    gate.release(4);
    assert(wait.wait(gate, {next}, 0ns) == ReleaseWaitResult::Complete);
}
