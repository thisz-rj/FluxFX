#include "transport.hpp"
#include "bricks.hpp"
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstring>
#include <memory>
namespace fluxfx {
static std::atomic<uint64_t> transport_bytes{0};
uint64_t transport_owned_bytes(){return transport_bytes.load();}
using TClock=std::chrono::steady_clock;
static double elapsed(TClock::time_point t){return std::chrono::duration<double,std::milli>(TClock::now()-t).count();}
static const char* shader_source=R"METAL(
#include <metal_stdlib>
using namespace metal;
struct Params {uint n,side,grid,sparse; float dx,dy,dz,pad; uint count;};
float fetch(device const float* src,device const int* map,int3 c,constant Params& p){
 c=clamp(c,int3(0),int3(p.n-1));
 if(!p.sparse)return src[(c.z*p.n+c.y)*p.n+c.x];
 int3 b=c/int(p.side);int slot=map[(b.z*p.grid+b.y)*p.grid+b.x];
 if(slot<0)return 0.;
 int3 v=c%int(p.side);
 return src[uint(slot)*p.side*p.side*p.side+(v.z*p.side+v.y)*p.side+v.x];
}
kernel void advect(device const float* src [[buffer(0)]],device float* dst [[buffer(1)]],
 device const int* map [[buffer(2)]],device const packed_int3* coords [[buffer(3)]],
 constant Params& p [[buffer(4)]],uint i [[thread_position_in_grid]]){
 if(i>=p.count)return;
 uint side=p.side;int3 cell;
 if(p.sparse){uint slot=i/(side*side*side),v=i%(side*side*side);
 cell=int3(coords[slot])*int(side)+int3(v%side,(v/side)%side,v/(side*side));}
 else cell=int3(i%p.n,(i/p.n)%p.n,i/(p.n*p.n));
 float3 offset=-float3(p.dx,p.dy,p.dz);float3 base=floor(offset);int3 lo=cell+int3(base);float3 f=offset-base;
 float a=mix(fetch(src,map,lo,p),fetch(src,map,lo+int3(1,0,0),p),f.x);
 float b=mix(fetch(src,map,lo+int3(0,1,0),p),fetch(src,map,lo+int3(1,1,0),p),f.x);
 float c=mix(fetch(src,map,lo+int3(0,0,1),p),fetch(src,map,lo+int3(1,0,1),p),f.x);
 float d=mix(fetch(src,map,lo+int3(0,1,1),p),fetch(src,map,lo+int3(1,1,1),p),f.x);
 dst[i]=mix(mix(a,b,f.y),mix(c,d,f.y),f.z);
}
)METAL";
struct Params {uint32_t n,side,grid,sparse;float dx,dy,dz,pad;uint32_t count;};
static_assert(sizeof(BrickCoord)==12,"packed coordinate layout");
struct Transport {
 id<MTLDevice> device;
 id<MTLCommandQueue> queue;
 id<MTLComputePipelineState> pipeline;
 id<MTLBuffer> buffer;
 uint64_t bytes=0,field_stride=0,map_offset=0,coords_offset=0;
 Params params{};
 bool swapped=false;
 Transport(id<MTLDevice> dev,id<MTLComputePipelineState> ps,Params p,
           const std::vector<int32_t>& map,const std::vector<BrickCoord>& coords,uint64_t budget):device(dev),pipeline(ps),params(p){
  queue=[device newCommandQueue];if(!queue)throw std::runtime_error("Transport queue unavailable");
  auto align=[](uint64_t n){return (n+255)&~uint64_t(255);};
  field_stride=align(uint64_t(p.count)*4);map_offset=2*field_stride;
  coords_offset=map_offset+align(map.size()*sizeof(int32_t));
  bytes=coords_offset+align(coords.size()*sizeof(BrickCoord));
  if(bytes>budget || bytes>device.maxBufferLength)throw std::invalid_argument("Transport buffers exceed per-engine budget");
  buffer=[device newBufferWithLength:bytes options:MTLResourceStorageModeShared];
  if(!buffer)throw std::runtime_error("Transport allocation failed");
  transport_bytes.fetch_add(bytes);
  auto* base=static_cast<char*>(buffer.contents);std::memset(base,0,bytes);
  std::memcpy(base+map_offset,map.data(),map.size()*sizeof(int32_t));
  std::memcpy(base+coords_offset,coords.data(),coords.size()*sizeof(BrickCoord));
  auto* field=reinterpret_cast<float*>(base);
  uint32_t extent=p.n*7/16,lower=(p.n-extent)/2;
  for(uint32_t i=0;i<p.count;++i){
   uint32_t x,y,z;
   if(p.sparse){auto c=coords[i/(p.side*p.side*p.side)];uint32_t v=i%(p.side*p.side*p.side);
    x=c.x*p.side+v%p.side;y=c.y*p.side+(v/p.side)%p.side;z=c.z*p.side+v/(p.side*p.side);}
   else{x=i%p.n;y=(i/p.n)%p.n;z=i/(p.n*p.n);}
   field[i]=(x>=lower && x<lower+extent && y>=lower && y<lower+extent && z>=lower && z<lower+extent)?1.f:0.f;
  }
 }
 ~Transport(){if(buffer){buffer=nil;transport_bytes.fetch_sub(bytes);}}
 double step(){
  @autoreleasepool {
   id<MTLCommandBuffer> command=[queue commandBuffer];
   id<MTLComputeCommandEncoder> encoder=[command computeCommandEncoder];
   if(!command || !encoder)throw std::runtime_error("Transport command unavailable");
   [encoder setComputePipelineState:pipeline];
   [encoder setBuffer:buffer offset:swapped?field_stride:0 atIndex:0];
   [encoder setBuffer:buffer offset:swapped?0:field_stride atIndex:1];
   [encoder setBuffer:buffer offset:map_offset atIndex:2];
   [encoder setBuffer:buffer offset:coords_offset atIndex:3];
   [encoder setBytes:&params length:sizeof(params) atIndex:4];
   auto width=std::min<NSUInteger>(256,pipeline.maxTotalThreadsPerThreadgroup);
   [encoder dispatchThreadgroups:MTLSizeMake((params.count+width-1)/width,1,1) threadsPerThreadgroup:MTLSizeMake(width,1,1)];
   [encoder endEncoding];[command commit];[command waitUntilCompleted];
   if(command.status!=MTLCommandBufferStatusCompleted)throw std::runtime_error(command.error.localizedDescription.UTF8String ?: "Transport GPU failure");
   swapped=!swapped;
   return command.GPUStartTime>0 && command.GPUEndTime>=command.GPUStartTime?(command.GPUEndTime-command.GPUStartTime)*1000:-1;
  }
 }
 const float* data()const{return reinterpret_cast<const float*>(static_cast<const char*>(buffer.contents)+(swapped?field_stride:0));}
};
TransportResult compare_transport(uint32_t n,uint32_t side,uint32_t steps,float dx,float dy,float dz,uint64_t budget){
 if((n!=32 && n!=64 && n!=128 && n!=256) || (side!=8 && side!=16) || !steps || steps>32 || !budget || budget>1024ull*1024*1024)
  throw std::invalid_argument("resolution 32/64/128/256; side 8/16; steps 1..32; budget <=1 GiB per engine");
 for(float v:{dx,dy,dz})if(!std::isfinite(v) || std::abs(v)>4)throw std::invalid_argument("Displacement must be finite, at most 4 voxels per step");
 TransportResult r{};r.resolution=n;r.side=side;r.steps=steps;
 auto start=TClock::now();uint32_t grid=n/side;
 uint32_t extent=n*7/16,lower=(n-extent)/2;
 // Each semi-Lagrangian step can extend nonzero support by ceil(abs(displacement))
 // cells per axis. Include interpolation diffusion, not only physical displacement.
 float delta[3]={dx,dy,dz};int lo[3],hi[3];
 for(int d=0;d<3;++d){int reach=int(std::ceil(std::abs(delta[d])))*int(steps)+1;
  lo[d]=std::max(0,int(lower)-(delta[d]<0?reach:1))/int(side);
  hi[d]=(std::min(int(n),int(lower+extent)+(delta[d]>0?reach:1))+int(side)-1)/int(side);}
 BrickTopology topology(grid*grid*grid);
 topology.activate_box({lo[0],lo[1],lo[2]},{hi[0]-lo[0],hi[1]-lo[1],hi[2]-lo[2]});
 r.active_bricks=uint32_t(topology.active().size());
 std::vector<int32_t> map(grid*grid*grid,-1);std::vector<BrickCoord> coords(r.active_bricks);
 for(auto slot:topology.active()){auto c=topology.coord(slot);coords[slot]=c;map[(c.z*grid+c.y)*grid+c.x]=int32_t(slot);}
 r.topology_ms=elapsed(start);r.initial_mass=double(extent)*extent*extent;
 @autoreleasepool {
  id<MTLDevice> device=MTLCreateSystemDefaultDevice();if(!device)throw std::runtime_error("No Metal device available");
  NSError* error=nil;MTLCompileOptions* options=[MTLCompileOptions new];options.fastMathEnabled=NO;
  id<MTLLibrary> lib=[device newLibraryWithSource:[NSString stringWithUTF8String:shader_source] options:options error:&error];
  if(!lib)throw std::runtime_error(error.localizedDescription.UTF8String ?: "Transport shader failed");
  id<MTLComputePipelineState> pipeline=[device newComputePipelineStateWithFunction:[lib newFunctionWithName:@"advect"] error:&error];
  if(!pipeline)throw std::runtime_error(error.localizedDescription.UTF8String ?: "Transport pipeline failed");
  Params p{n,side,grid,1,dx,dy,dz,0,r.active_bricks*side*side*side};
  start=TClock::now();Transport sparse(device,pipeline,p,map,coords,budget);r.sparse_setup_ms=elapsed(start);r.sparse_bytes=sparse.bytes;
  p.sparse=0;p.count=n*n*n;
  start=TClock::now();Transport dense(device,pipeline,p,{-1},{{0,0,0}},budget);r.dense_setup_ms=elapsed(start);r.dense_bytes=dense.bytes;
  // Alternate order to reduce systematic scheduling bias; no CPU readback per step.
  for(uint32_t i=0;i<steps;++i){
   if(i%2){start=TClock::now();r.dense_gpu_ms.push_back(dense.step());r.dense_wall_ms+=elapsed(start);}
   start=TClock::now();r.sparse_gpu_ms.push_back(sparse.step());r.sparse_wall_ms+=elapsed(start);
   if(!(i%2)){start=TClock::now();r.dense_gpu_ms.push_back(dense.step());r.dense_wall_ms+=elapsed(start);}
  }
  r.density.resize(size_t(n)*n*n);auto* a=sparse.data();auto* b=dense.data();double sq=0;
  for(uint32_t z=0;z<n;++z)for(uint32_t y=0;y<n;++y)for(uint32_t x=0;x<n;++x){
   auto dense_i=(z*n+y)*n+x;auto slot=map[((z/side)*grid+y/side)*grid+x/side];
   float v=slot<0?0:a[uint32_t(slot)*side*side*side+((z%side)*side+y%side)*side+x%side];
   if(!std::isfinite(v) || !std::isfinite(b[dense_i]))throw std::runtime_error("Nonfinite transport output");
   double e=std::abs(double(v)-b[dense_i]);r.max_error=std::max(r.max_error,e);sq+=e*e;
   r.sparse_mass+=v;r.dense_mass+=b[dense_i];r.density[dense_i]=v;
  }
  r.rms_error=std::sqrt(sq/(double(n)*n*n));
 }
 return r;
}
}
