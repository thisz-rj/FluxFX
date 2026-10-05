#pragma once
#include <cstdint>
#include <vector>
namespace fluxfx {
struct TransportResult {
    uint32_t resolution,side,steps,active_bricks;
    uint64_t sparse_bytes,dense_bytes;
    double topology_ms,sparse_setup_ms,dense_setup_ms,sparse_wall_ms,dense_wall_ms;
    double max_error,rms_error,sparse_mass,dense_mass,initial_mass;
    std::vector<double> sparse_gpu_ms,dense_gpu_ms;
    std::vector<float> density;
};
uint64_t transport_owned_bytes();
TransportResult compare_transport(uint32_t resolution,uint32_t side,uint32_t steps,
                                 float dx,float dy,float dz,uint64_t budget);
}
