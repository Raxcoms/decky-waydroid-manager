#pragma once

#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <mutex>
#include <unordered_map>
#include <vector>

namespace waydroid_manager {

struct ReleaseToken {
    unsigned id = 0;
    uint64_t generation = 0;
    explicit operator bool() const { return generation != 0; }
};

class ReleaseGate {
public:
    void submit(unsigned id) {
        std::lock_guard<std::mutex> lock(mutex_);
        ++states_[id].submitted;
    }

    void release(unsigned id) {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            auto it = states_.find(id);
            if (it == states_.end()) return;
            it->second.released = it->second.submitted;
        }
        changed_.notify_all();
    }

    void forget(unsigned id) {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            states_.erase(id);
        }
        changed_.notify_all();
    }

    ReleaseToken snapshot(unsigned id) {
        std::lock_guard<std::mutex> lock(mutex_);
        auto it = states_.find(id);
        if (it == states_.end() || it->second.submitted == it->second.released) return {};
        return {id, it->second.submitted};
    }

    bool wait(const std::vector<ReleaseToken>& tokens, std::chrono::nanoseconds timeout) {
        std::unique_lock<std::mutex> lock(mutex_);
        return changed_.wait_for(lock, timeout, [&] {
            return std::all_of(tokens.begin(), tokens.end(), [&](const ReleaseToken& token) {
                auto it = states_.find(token.id);
                return it == states_.end() || it->second.released >= token.generation;
            });
        });
    }

private:
    struct State { uint64_t submitted = 0; uint64_t released = 0; };
    std::mutex mutex_;
    std::condition_variable changed_;
    std::unordered_map<unsigned, State> states_;
};

enum class ReleaseWaitResult { Complete, TimedOut, Deferred };

class ReleaseWait {
public:
    ReleaseWaitResult wait(ReleaseGate& gate, const std::vector<ReleaseToken>& tokens,
                           std::chrono::nanoseconds timeout) {
        if (!stalled_.empty()) {
            if (!gate.wait(stalled_, std::chrono::nanoseconds::zero())) return ReleaseWaitResult::Deferred;
            stalled_.clear();
        }
        if (gate.wait(tokens, timeout)) return ReleaseWaitResult::Complete;
        stalled_ = tokens;
        return ReleaseWaitResult::TimedOut;
    }

private:
    std::vector<ReleaseToken> stalled_;
};

}
