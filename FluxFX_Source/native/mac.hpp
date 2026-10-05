#pragma once
#include <cstdint>
#include <vector>
namespace fluxfx {
struct MacResult {
 uint32_t resolution,side,steps,active_bricks;
 uint64_t sparse_bytes,dense_bytes,owned_faces,padding_faces;
 double max_error,rms_error,padding_error,topology_ms,sparse_wall_ms,dense_wall_ms;
 std::vector<double> sparse_gpu_ms,dense_gpu_ms;
 std::vector<float> faces;
};
uint64_t mac_owned_bytes();
MacResult compare_mac(uint32_t n,uint32_t side,uint32_t steps,uint32_t mode,uint64_t budget);
}
