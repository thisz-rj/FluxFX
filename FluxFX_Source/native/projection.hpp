#pragma once
#include <cstdint>
#include <vector>
namespace fluxfx {
struct ProjectionResult {
 uint32_t resolution,side,iterations,mode,active_bricks,solve_cells,cycles,levels,steps,schedule,dense_full,global_support,hybrid,density_cells,density_bricks,adaptive,expansions,pooled,density_capacity,density_reallocations,density_reuses;
 uint64_t global_copy_bytes,preserved_bytes,peak_sparse_bytes,density_bytes,sparse_bytes,dense_bytes,sparse_hierarchy_bytes,dense_hierarchy_bytes;
 double preflight_ms,density_topology_ms,divergence_error,dense_after_rms,density_error,sparse_mass,dense_mass,injected_mass,topology_ms;
 double max_error,pressure_error,before_rms,after_rms,residual_rms,wall_error,padding_error;
 double sparse_wall_ms,dense_wall_ms,sparse_gpu_ms,dense_gpu_ms;
 std::vector<float> faces,pressure,before,after,density;
};
uint64_t projection_owned_bytes();
ProjectionResult compare_projection(uint32_t n,uint32_t side,uint32_t iterations,uint32_t mode,uint64_t budget,uint32_t cycles=0,uint32_t steps=0,uint32_t schedule=0,bool dense_full=false,bool global_support=false,bool hybrid=false,bool adaptive=false,bool pooled=false);
}
