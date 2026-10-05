#pragma once
#include <cstdint>
#include <string>
#include <vector>
namespace fluxfx {
struct ProbeResult {
    std::string device;
    bool unified;
    uint64_t max_buffer_bytes, buffer_bytes;
    uint32_t count, repeats, seed, mismatches;
    double setup_ms, submit_wait_ms, verify_ms;
    std::vector<double> gpu_ms;
};
uint64_t owned_buffer_bytes();
ProbeResult probe(uint32_t count, uint32_t repeats, uint32_t seed);
}
