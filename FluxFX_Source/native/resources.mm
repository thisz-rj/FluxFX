#include "resources.hpp"
#include "arena.hpp"
#include "brick_pool.hpp"
#include <cstring>
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <chrono>

namespace fluxfx {
static std::atomic<uint64_t> resident_bytes{0};
uint64_t arena_owned_buffer_bytes() { return resident_bytes.load(); }
using Clock=std::chrono::steady_clock;
static double ms(Clock::time_point start) { return std::chrono::duration<double,std::milli>(Clock::now()-start).count(); }
struct Context::Impl {
    id<MTLDevice> device;
    id<MTLCommandQueue> queue;
    id<MTLComputePipelineState> pipeline;
    id<MTLComputePipelineState> brick_pipeline;
    id<MTLBuffer> buffer;
    std::unique_ptr<Arena> arena;
    ResourceStats info{};
    void ready() const { if(info.closed) throw std::runtime_error("Native context is closed"); }
    const Span& checked(uint64_t id,uint32_t count) const {
        ready();const auto& span=arena->get(id);
        if (!count || count>16777216 || uint64_t(count)*4>span.requested)
            throw std::invalid_argument("Dispatch/verify count exceeds allocation or 16777216-element probe limit");
        return span;
    }
    ~Impl() { if(buffer) { buffer=nil;resident_bytes.fetch_sub(info.budget); } }
};
Context::Context(uint64_t budget):impl(new Impl) {
    if (!budget || budget%256 || budget>1024ull*1024*1024)
        throw std::invalid_argument("Arena budget must be 256-byte aligned, between 256 bytes and 1 GiB");
    @autoreleasepool {
        auto& p=*impl;p.info.budget=budget;
        p.device=MTLCreateSystemDefaultDevice();
        if(!p.device) throw std::runtime_error("No Metal device available");
        p.info.device=p.device.name.UTF8String;p.info.unified=p.device.hasUnifiedMemory;
        p.info.max_buffer=p.device.maxBufferLength;p.info.recommended_working_set=p.device.recommendedMaxWorkingSetSize;
        if(budget>p.info.max_buffer) throw std::invalid_argument("Arena budget exceeds Metal maximum buffer length");
        p.queue=[p.device newCommandQueue];
        if(!p.queue) throw std::runtime_error("Metal queue creation failed");
        NSError* error=nil;
        NSString* source=@"#include <metal_stdlib>\nusing namespace metal;\n"
          "kernel void fill(device uint* out [[buffer(0)]], constant uint& n [[buffer(1)]],"
          "constant uint& seed [[buffer(2)]], uint i [[thread_position_in_grid]]) {"
          "if(i<n) out[i]=(i^seed)*1664525u+1013904223u; }";
        id<MTLLibrary> library=[p.device newLibraryWithSource:source options:nil error:&error];
        if(!library) throw std::runtime_error(error.localizedDescription.UTF8String ?: "Metal compilation failed");
        id<MTLFunction> function=[library newFunctionWithName:@"fill"];
        p.pipeline=[p.device newComputePipelineStateWithFunction:function error:&error];
        if(!p.pipeline) throw std::runtime_error(error.localizedDescription.UTF8String ?: "Metal pipeline failed");
        p.info.thread_width=p.pipeline.threadExecutionWidth;p.info.max_threads=p.pipeline.maxTotalThreadsPerThreadgroup;
        p.arena=std::make_unique<Arena>(budget);
        p.buffer=[p.device newBufferWithLength:budget options:MTLResourceStorageModeShared];
        if(!p.buffer) throw std::runtime_error("Arena backing buffer allocation failed");
        resident_bytes.fetch_add(budget);
    }
}
Context::~Context()=default;
uint64_t Context::allocate(uint64_t bytes) { impl->ready();return impl->arena->allocate(bytes); }
void Context::release(uint64_t id) { impl->ready();impl->arena->release(id); }
void Context::close() {
    if(impl->info.closed) return;
    @autoreleasepool {
        impl->buffer=nil;resident_bytes.fetch_sub(impl->info.budget);
        impl->brick_pipeline=nil;impl->pipeline=nil;impl->queue=nil;impl->device=nil;impl->arena.reset();impl->info.closed=true;
    }
}
ResourceStats Context::stats() const {
    auto r=impl->info;
    if(!r.closed) {
        r.resident=r.budget;r.used=impl->arena->used;r.peak=impl->arena->peak;
        r.active=impl->arena->count();r.allocations=impl->arena->allocations;r.largest_free=impl->arena->largest_free();
    }
    return r;
}
uint32_t Context::verify(uint64_t id,uint32_t count,uint32_t seed) {
    const auto& span=impl->checked(id,count);
    const void* base=impl->buffer.contents;
    if(!base) throw std::runtime_error("Arena is not CPU accessible");
    auto* ptr=reinterpret_cast<const uint32_t*>(static_cast<const char*>(base)+span.offset);
    uint32_t mismatch=0;
    for(uint32_t i=0;i<count;++i) if(ptr[i]!=((i^seed)*1664525u+1013904223u)) ++mismatch;
    return mismatch;
}
ProbeResult Context::dispatch(uint64_t allocation,uint32_t count,uint32_t repeats,uint32_t seed) {
    const auto& span=impl->checked(allocation,count);
    if(!repeats || repeats>32) throw std::invalid_argument("Use 1..32 dispatches");
    ProbeResult r{};r.device=impl->info.device;r.unified=impl->info.unified;r.max_buffer_bytes=impl->info.max_buffer;
    r.buffer_bytes=span.bytes;r.count=count;r.repeats=repeats;r.seed=seed;
    @autoreleasepool {
        auto start=Clock::now();
        for(uint32_t i=0;i<repeats;++i) {
            @autoreleasepool {
                id<MTLCommandBuffer> command=[impl->queue commandBuffer];
                id<MTLComputeCommandEncoder> encoder=[command computeCommandEncoder];
                if(!command || !encoder) throw std::runtime_error("Metal command creation failed");
                uint32_t current=seed+i;
                [encoder setComputePipelineState:impl->pipeline];
                [encoder setBuffer:impl->buffer offset:span.offset atIndex:0];
                [encoder setBytes:&count length:sizeof(count) atIndex:1];
                [encoder setBytes:&current length:sizeof(current) atIndex:2];
                auto width=std::min<uint64_t>(256,impl->info.max_threads);
                [encoder dispatchThreadgroups:MTLSizeMake((count+width-1)/width,1,1) threadsPerThreadgroup:MTLSizeMake(width,1,1)];
                [encoder endEncoding];[command commit];[command waitUntilCompleted];
                if(command.status!=MTLCommandBufferStatusCompleted) throw std::runtime_error(command.error.localizedDescription.UTF8String ?: "GPU execution failed");
                double begin=command.GPUStartTime,end=command.GPUEndTime;
                r.gpu_ms.push_back(begin>0 && end>=begin ? (end-begin)*1000 : -1);
            }
        }
        r.submit_wait_ms=ms(start);start=Clock::now();r.mismatches=verify(allocation,count,seed+repeats-1);r.verify_ms=ms(start);
    }
    return r;
}
}

namespace fluxfx {
ProbeResult Context::brick_probe(uint64_t allocation,uint32_t side,uint32_t capacity,
    const std::vector<uint32_t>& active,const std::vector<int32_t>& neighbors,
    uint32_t repeats,double& prepare_ms) {
    impl->ready();const auto& span=impl->arena->get(allocation);
    const uint32_t voxels=side*side*side;
    const uint64_t field_bytes=uint64_t(capacity)*voxels*4;
    if((side!=8 && side!=16) || !capacity || !repeats || repeats>32 ||
       active.size()>capacity || neighbors.size()!=size_t(capacity)*6 ||
       field_bytes+uint64_t(capacity)*28>span.requested)
        throw std::invalid_argument("Invalid brick dispatch layout");
    for(auto slot:active)if(slot>=capacity)throw std::invalid_argument("Invalid active slot");
    ProbeResult r{};r.device=impl->info.device;r.repeats=repeats;
    @autoreleasepool {
        if(!impl->brick_pipeline) {
            NSError* error=nil;
            NSString* src=@"#include <metal_stdlib>\nusing namespace metal;\n"
            "kernel void bricks(device uint* field [[buffer(0)]],device const uint* ids [[buffer(1)]],"
            "device const int* nb [[buffer(2)]],constant uint& voxels [[buffer(3)]],"
            "uint3 local [[thread_position_in_grid]],uint3 group [[threadgroup_position_in_grid]]) {"
            "uint slot=ids[group.y];uint v=local.x; if(v>=voxels)return;"
            "uint value=(slot+1u)*1664525u+v;"
            "for(uint d=0;d<6;++d)value=value*33u+uint(nb[slot*6+d]+1);"
            "field[slot*voxels+v]=value;}";
            id<MTLLibrary> lib=[impl->device newLibraryWithSource:src options:nil error:&error];
            if(!lib)throw std::runtime_error(error.localizedDescription.UTF8String ?: "Brick shader compilation failed");
            id<MTLFunction> function=[lib newFunctionWithName:@"bricks"];
            impl->brick_pipeline=[impl->device newComputePipelineStateWithFunction:function error:&error];
            if(!impl->brick_pipeline)throw std::runtime_error(error.localizedDescription.UTF8String ?: "Brick pipeline failed");
        }
        auto start=Clock::now();auto* base=static_cast<char*>(impl->buffer.contents)+span.offset;
        std::memset(base,0xcd,field_bytes);
        std::memcpy(base+field_bytes,active.data(),active.size()*sizeof(uint32_t));
        std::memcpy(base+field_bytes+uint64_t(capacity)*4,neighbors.data(),neighbors.size()*sizeof(int32_t));
        prepare_ms=ms(start);start=Clock::now();
        for(uint32_t i=0;i<repeats && !active.empty();++i) {
            @autoreleasepool {
                id<MTLCommandBuffer> command=[impl->queue commandBuffer];
                id<MTLComputeCommandEncoder> encoder=[command computeCommandEncoder];
                if(!command || !encoder)throw std::runtime_error("Brick command creation failed");
                [encoder setComputePipelineState:impl->brick_pipeline];
                [encoder setBuffer:impl->buffer offset:span.offset atIndex:0];
                [encoder setBuffer:impl->buffer offset:span.offset+field_bytes atIndex:1];
                [encoder setBuffer:impl->buffer offset:span.offset+field_bytes+uint64_t(capacity)*4 atIndex:2];
                [encoder setBytes:&voxels length:sizeof(voxels) atIndex:3];
                NSUInteger width=std::min<NSUInteger>(256,impl->brick_pipeline.maxTotalThreadsPerThreadgroup);
                [encoder dispatchThreadgroups:MTLSizeMake((voxels+width-1)/width,active.size(),1) threadsPerThreadgroup:MTLSizeMake(width,1,1)];
                [encoder endEncoding];[command commit];[command waitUntilCompleted];
                if(command.status!=MTLCommandBufferStatusCompleted)throw std::runtime_error(command.error.localizedDescription.UTF8String ?: "Brick GPU execution failed");
                double begin=command.GPUStartTime,end=command.GPUEndTime;
                r.gpu_ms.push_back(begin>0 && end>=begin?(end-begin)*1000:-1);
            }
        }
        r.submit_wait_ms=ms(start);start=Clock::now();
        // Includes every inactive slot, detecting writes outside the active list.
        std::vector<bool> live(capacity,false);for(auto slot:active)live[slot]=true;
        const auto* field=reinterpret_cast<const uint32_t*>(base);
        for(uint32_t slot=0;slot<capacity;++slot)for(uint32_t v=0;v<voxels;++v) {
            uint32_t expected=0xcdcdcdcdu;
            if(live[slot]) {
                expected=(slot+1u)*1664525u+v;
                for(uint32_t d=0;d<6;++d)expected=expected*33u+uint32_t(neighbors[slot*6+d]+1);
            }
            if(field[uint64_t(slot)*voxels+v]!=expected)++r.mismatches;
        }
        r.verify_ms=ms(start);
    }
    return r;
}
BrickReport BrickPool::probe(uint32_t repeats) {
    ready();if(!repeats || repeats>32)throw std::invalid_argument("Use 1..32 dispatches");
    BrickReport r{};auto start=Clock::now();
    std::fill(neighbors_.begin(),neighbors_.end(),-1);
    for(auto slot:topology_.active()) {
        auto n=topology_.neighbors(topology_.coord(slot));
        std::copy(n.begin(),n.end(),neighbors_.begin()+size_t(slot)*6);
    }
    r.topology_ms=ms(start);r.active_voxels=uint64_t(topology_.active().size())*side_*side_*side_;
    r.probe=context_.brick_probe(allocation_,side_,topology_.capacity(),topology_.active(),neighbors_,repeats,r.prepare_ms);
    return r;
}
}
