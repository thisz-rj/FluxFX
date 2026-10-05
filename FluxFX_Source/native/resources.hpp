#pragma once
#include "core.hpp"
#include <memory>
namespace fluxfx {
struct ResourceStats {
    std::string device;
    bool closed, unified;
    uint64_t budget, resident, used, peak, active, allocations, largest_free;
    uint64_t max_buffer, recommended_working_set, thread_width, max_threads;
};
class Context {
    struct Impl;
    std::unique_ptr<Impl> impl;
public:
    explicit Context(uint64_t budget);
    ~Context();
    uint64_t allocate(uint64_t bytes);
    void release(uint64_t id);
    ProbeResult dispatch(uint64_t id,uint32_t count,uint32_t repeats,uint32_t seed);
    uint32_t verify(uint64_t id,uint32_t count,uint32_t seed);
    ProbeResult brick_probe(uint64_t id, uint32_t side, uint32_t capacity,
        const std::vector<uint32_t>& active, const std::vector<int32_t>& neighbors,
        uint32_t repeats, double& prepare_ms);
    ResourceStats stats() const;
    void close();
};
uint64_t arena_owned_buffer_bytes();
}
