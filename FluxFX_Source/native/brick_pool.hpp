#pragma once
#include "bricks.hpp"
#include "regions.hpp"
#include "resources.hpp"
namespace fluxfx {
struct BrickReport { ProbeResult probe; double topology_ms,prepare_ms; uint64_t active_voxels; };
class BrickPool {
    uint32_t side_;
    BrickTopology topology_;
    RegionTracker regions_;
    Context context_;
    uint64_t allocation_;
    std::vector<int32_t> neighbors_;
    bool closed_=false;
    static uint64_t bytes(uint32_t side,uint32_t capacity) {
        if(side!=8 && side!=16)throw std::invalid_argument("Brick side must be 8 or 16");
        if(!capacity || capacity>262144)throw std::invalid_argument("Brick capacity must be 1..262144");
        uint64_t n=uint64_t(capacity)*(uint64_t(side)*side*side*4+28);
        return (n+255)&~uint64_t(255);
    }
public:
    BrickPool(uint32_t side,uint32_t capacity,uint64_t budget):side_(side),topology_(capacity),regions_(capacity),
        context_(checked_budget(side,capacity,budget)),allocation_(context_.allocate(bytes(side,capacity))),neighbors_(size_t(capacity)*6,-1) {}
    static uint64_t checked_budget(uint32_t side,uint32_t capacity,uint64_t budget) {
        if(bytes(side,capacity)>budget)throw std::invalid_argument("Brick payload and GPU topology exceed budget");
        return budget;
    }
    void ready() const {if(closed_)throw std::runtime_error("Brick pool is closed");}
    BrickTopology& topology() {ready();return topology_;}
    RegionTracker& regions() {ready();return regions_;}
    uint32_t side() const {return side_;}
    ResourceStats stats() const {return context_.stats();}
    uint64_t cpu_bytes() const {return regions_.bytes()+topology_.metadata_bytes()+neighbors_.capacity()*sizeof(int32_t);}
    BrickReport probe(uint32_t repeats);
    void close() {context_.close();closed_=true;}
};
}
