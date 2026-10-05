#include "core.hpp"
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <chrono>
#include <stdexcept>
#include <algorithm>
#include <atomic>

namespace fluxfx {
static std::atomic<uint64_t> live_bytes{0};
uint64_t owned_buffer_bytes() { return live_bytes.load(); }
struct OwnedBuffer {
    id<MTLBuffer> buffer;
    uint64_t bytes;
    OwnedBuffer(id<MTLDevice> device, uint64_t size):
        buffer([device newBufferWithLength:size options:MTLResourceStorageModeShared]), bytes(size) {
        if (!buffer) throw std::runtime_error("Probe buffer allocation failed");
        live_bytes.fetch_add(bytes);
    }
    ~OwnedBuffer() { buffer=nil; live_bytes.fetch_sub(bytes); }
    OwnedBuffer(const OwnedBuffer&)=delete;
    OwnedBuffer& operator=(const OwnedBuffer&)=delete;
};
using Clock = std::chrono::steady_clock;
static double elapsed(Clock::time_point start) {
    return std::chrono::duration<double, std::milli>(Clock::now()-start).count();
}
static std::runtime_error failure(const char* stage, NSError* error) {
    return std::runtime_error(std::string(stage)+": "+(error ? error.localizedDescription.UTF8String : "Metal returned nil"));
}
ProbeResult probe(uint32_t count, uint32_t repeats, uint32_t seed) {
    if (!count || count > 16777216 || !repeats || repeats > 32)
        throw std::invalid_argument("Use 1..16777216 uint32 elements and 1..32 dispatches");
    ProbeResult result{};
    result.count=count; result.repeats=repeats; result.seed=seed;
    // ARC strong locals and autoreleased command objects are destroyed at this
    // boundary, including every exception path. No native GPU state is global.
    @autoreleasepool {
        auto start=Clock::now();
        id<MTLDevice> device=MTLCreateSystemDefaultDevice();
        if (!device) throw std::runtime_error("No Metal device available");
        result.device=device.name.UTF8String;
        result.unified=device.hasUnifiedMemory;
        result.max_buffer_bytes=device.maxBufferLength;
        result.buffer_bytes=uint64_t(count)*sizeof(uint32_t);
        if (result.buffer_bytes > result.max_buffer_bytes) throw std::runtime_error("Probe exceeds Metal buffer limit");
        id<MTLCommandQueue> queue=[device newCommandQueue];
        if (!queue) throw std::runtime_error("Metal queue allocation failed");
        NSString* source=@"#include <metal_stdlib>\nusing namespace metal;\n"
          "kernel void probe(device uint* out [[buffer(0)]], constant uint& n [[buffer(1)]],"
          "constant uint& seed [[buffer(2)]], uint i [[thread_position_in_grid]]) {"
          "if(i<n) out[i]=(i^seed)*1664525u+1013904223u; }";
        NSError* error=nil;
        id<MTLLibrary> library=[device newLibraryWithSource:source options:nil error:&error];
        if (!library) throw failure("Kernel compilation",error);
        id<MTLFunction> function=[library newFunctionWithName:@"probe"];
        if (!function) throw std::runtime_error("Probe kernel is missing");
        id<MTLComputePipelineState> pipeline=[device newComputePipelineStateWithFunction:function error:&error];
        if (!pipeline) throw failure("Pipeline creation",error);
        OwnedBuffer output(device,result.buffer_bytes);
        result.setup_ms=elapsed(start);
        auto submit=Clock::now();
        for (uint32_t step=0;step<repeats;++step) {
            @autoreleasepool {
                id<MTLCommandBuffer> command=[queue commandBuffer];
                id<MTLComputeCommandEncoder> encoder=[command computeCommandEncoder];
                if (!command || !encoder) throw std::runtime_error("Metal command allocation failed");
                uint32_t current_seed=seed+step;
                [encoder setComputePipelineState:pipeline];
                [encoder setBuffer:output.buffer offset:0 atIndex:0];
                [encoder setBytes:&count length:sizeof(count) atIndex:1];
                [encoder setBytes:&current_seed length:sizeof(current_seed) atIndex:2];
                NSUInteger width=std::min<NSUInteger>(256,pipeline.maxTotalThreadsPerThreadgroup);
                [encoder dispatchThreadgroups:MTLSizeMake((count+width-1)/width,1,1)
                       threadsPerThreadgroup:MTLSizeMake(width,1,1)];
                [encoder endEncoding];
                [command commit];
                [command waitUntilCompleted];
                if (command.status != MTLCommandBufferStatusCompleted) throw failure("GPU execution",command.error);
                double begin=command.GPUStartTime, end=command.GPUEndTime;
                result.gpu_ms.push_back(begin>0 && end>=begin ? (end-begin)*1000 : -1);
            }
        }
        result.submit_wait_ms=elapsed(submit);
        auto verify=Clock::now();
        const uint32_t* values=static_cast<const uint32_t*>(output.buffer.contents);
        if (!values) throw std::runtime_error("Shared buffer is not CPU accessible");
        uint32_t last_seed=seed+repeats-1;
        for (uint32_t i=0;i<count;++i)
            if (values[i] != ((i^last_seed)*1664525u+1013904223u)) ++result.mismatches;
        result.verify_ms=elapsed(verify);
    }
    return result;
}

} // namespace fluxfx
