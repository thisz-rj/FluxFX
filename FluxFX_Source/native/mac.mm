#include "mac.hpp"
#include "bricks.hpp"
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstring>
namespace fluxfx {
static std::atomic<uint64_t> mac_bytes{0};
uint64_t mac_owned_bytes(){return mac_bytes.load();}
using MClock=std::chrono::steady_clock;
static double milliseconds(MClock::time_point t){return std::chrono::duration<double,std::milli>(MClock::now()-t).count();}
static const char* mac_source=R"METAL(
#include <metal_stdlib>
using namespace metal;
struct P {uint n,side,grid,sparse,axis,count;};
uint3 shape(uint n,uint axis){uint3 s(n);s[axis]++;return s;}
float getFace(device const float* field,device const int* map,int3 c,uint axis,constant P& p){
 uint3 dims=shape(p.n,axis);c=clamp(c,int3(0),int3(dims)-1);
 if(!p.sparse)return field[axis*p.count+(c.z*dims.y+c.y)*dims.x+c.x];
 int3 b=c/int(p.side);b[axis]=min(b[axis],int(p.grid)-1);
 int slot=map[(b.z*p.grid+b.y)*p.grid+b.x];if(slot<0)return 0.;
 int3 local=c-b*int(p.side);uint3 block=shape(p.side,axis);
 uint per=(p.side+1)*p.side*p.side;
 return field[axis*p.count+uint(slot)*per+(local.z*block.y+local.y)*block.x+local.x];
}
float sampleFace(device const float* field,device const int* map,float3 q,uint axis,constant P& p){
 q=clamp(q,float3(0),float3(shape(p.n,axis)-1));int3 b=int3(floor(q));float3 f=q-float3(b);
 float result=0.;
 for(int z=0;z<2;z++)for(int y=0;y<2;y++)for(int x=0;x<2;x++){
  float3 w=mix(1.-f,f,float3(x,y,z));result+=w.x*w.y*w.z*getFace(field,map,b+int3(x,y,z),axis,p);
 }
 return result;
}
float3 offset(uint axis){float3 o(.5);o[axis]=0.;return o;}
float3 velocity(device const float* field,device const int* map,float3 pos,constant P& p){
 return float3(sampleFace(field,map,pos-offset(0),0,p),sampleFace(field,map,pos-offset(1),1,p),sampleFace(field,map,pos-offset(2),2,p));
}
kernel void advect_mac(device const float* src [[buffer(0)]],device float* dst [[buffer(1)]],
 device const int* map [[buffer(2)]],device const packed_int3* coords [[buffer(3)]],
 constant P& p [[buffer(4)]],uint i [[thread_position_in_grid]]){
 if(i>=p.count)return;int3 c;
 if(p.sparse){uint per=(p.side+1)*p.side*p.side,slot=i/per,v=i%per;uint3 dims=shape(p.side,p.axis);
 int3 local=int3(v%dims.x,(v/dims.x)%dims.y,v/(dims.x*dims.y));int3 brick=int3(coords[slot]);
 // Interior upper planes are padding: the brick on the positive side owns the face.
 if(local[p.axis]==int(p.side) && brick[p.axis]!=int(p.grid)-1)return;
 c=brick*int(p.side)+local;
 }else{uint3 dims=shape(p.n,p.axis);c=int3(i%dims.x,(i/dims.x)%dims.y,i/(dims.x*dims.y));}
 float3 pos=float3(c)+offset(p.axis);
 float3 midpoint=pos-.5*velocity(src,map,pos,p);
 float3 departure=pos-velocity(src,map,midpoint,p);
 dst[p.axis*p.count+i]=sampleFace(src,map,departure-offset(p.axis),p.axis,p);
}
)METAL";
struct MP {uint32_t n,side,grid,sparse,axis,count;};
static uint32_t index3(uint32_t x,uint32_t y,uint32_t z,uint32_t n,uint32_t axis){
 uint32_t sx=n+(axis==0),sy=n+(axis==1);return (z*sy+y)*sx+x;
}
static BrickCoord cell3(uint32_t i,uint32_t n,uint32_t axis){
 uint32_t sx=n+(axis==0),sy=n+(axis==1);return {int(i%sx),int((i/sx)%sy),int(i/(sx*sy))};
}
static float initial(BrickCoord c,uint32_t axis,uint32_t n,uint32_t mode){
 float p[3]={c.x+.5f,c.y+.5f,c.z+.5f};p[axis]-=.5f;
 if(mode==0 || mode==3){float lo=n*.25f,hi=n*.75f;for(float v:p)if(v<lo || v>=hi)return 0.f;}
 if(mode==2)return axis==0?.25f:axis==1?-.125f:.0625f;
 if(mode==3)return axis==0?.35f:axis==1?-.2f:.1f;
 // Signed affine field: component and coordinate dependent, including cross terms.
 return (.1f*(axis+1)) + .2f*(p[(axis+1)%3]/n-.5f)-.3f*(p[(axis+2)%3]/n-.5f);
}
struct MacEngine {
 id<MTLDevice> device;id<MTLComputePipelineState> pipeline;id<MTLCommandQueue> queue;id<MTLBuffer> buffer;
 MP p;uint64_t bytes=0,stride=0,map_offset=0,coords_offset=0;bool swapped=false;
 MacEngine(id<MTLDevice> d,id<MTLComputePipelineState> ps,MP params,const std::vector<int32_t>& map,
           const std::vector<BrickCoord>& coords,uint32_t mode,uint64_t budget):device(d),pipeline(ps),p(params){
  auto align=[](uint64_t v){return (v+255)&~uint64_t(255);};
  stride=align(uint64_t(p.count)*3*4);map_offset=2*stride;coords_offset=map_offset+align(map.size()*4);
  bytes=coords_offset+align(coords.size()*sizeof(BrickCoord));
  if(bytes>budget || bytes>d.maxBufferLength)throw std::invalid_argument("MAC buffers exceed per-engine budget");
  queue=[device newCommandQueue];if(!queue)throw std::runtime_error("MAC queue unavailable");
  buffer=[device newBufferWithLength:bytes options:MTLResourceStorageModeShared];if(!buffer)throw std::runtime_error("MAC allocation failed");
  mac_bytes.fetch_add(bytes);auto* base=static_cast<char*>(buffer.contents);std::memset(base,0,bytes);
  std::memcpy(base+map_offset,map.data(),map.size()*4);std::memcpy(base+coords_offset,coords.data(),coords.size()*sizeof(BrickCoord));
  uint32_t per=(p.side+1)*p.side*p.side;
  for(uint32_t axis=0;axis<3;++axis)for(uint32_t i=0;i<p.count;++i){
   BrickCoord c;bool padding=false;
   if(p.sparse){auto b=coords[i/per];c=cell3(i%per,p.side,axis);
    int local[3]={c.x,c.y,c.z},brick[3]={b.x,b.y,b.z};padding=local[axis]==int(p.side) && brick[axis]!=int(p.grid)-1;
    c={b.x*int(p.side)+c.x,b.y*int(p.side)+c.y,b.z*int(p.side)+c.z};}
   else c=cell3(i,p.n,axis);
   reinterpret_cast<float*>(base)[axis*p.count+i]=padding?12345.f:initial(c,axis,p.n,mode);
   reinterpret_cast<float*>(base+stride)[axis*p.count+i]=padding?12345.f:0.f;
  }
 }
 ~MacEngine(){if(buffer){buffer=nil;mac_bytes.fetch_sub(bytes);}}
 double step(){@autoreleasepool {
  id<MTLCommandBuffer> cmd=[queue commandBuffer];id<MTLComputeCommandEncoder> enc=[cmd computeCommandEncoder];
  if(!cmd || !enc)throw std::runtime_error("MAC encoder unavailable");
  [enc setComputePipelineState:pipeline];[enc setBuffer:buffer offset:swapped?stride:0 atIndex:0];
  [enc setBuffer:buffer offset:swapped?0:stride atIndex:1];[enc setBuffer:buffer offset:map_offset atIndex:2];[enc setBuffer:buffer offset:coords_offset atIndex:3];
  auto width=std::min<NSUInteger>(256,pipeline.maxTotalThreadsPerThreadgroup);
  for(uint32_t axis=0;axis<3;++axis){p.axis=axis;[enc setBytes:&p length:sizeof(p) atIndex:4];
   [enc dispatchThreadgroups:MTLSizeMake((p.count+width-1)/width,1,1) threadsPerThreadgroup:MTLSizeMake(width,1,1)];}
  [enc endEncoding];[cmd commit];[cmd waitUntilCompleted];
  if(cmd.status!=MTLCommandBufferStatusCompleted)throw std::runtime_error(cmd.error.localizedDescription.UTF8String ?: "MAC dispatch failed");
  swapped=!swapped;return cmd.GPUStartTime>0 && cmd.GPUEndTime>=cmd.GPUStartTime?(cmd.GPUEndTime-cmd.GPUStartTime)*1000:-1;
 }}
 const float* data()const{return reinterpret_cast<const float*>(static_cast<const char*>(buffer.contents)+(swapped?stride:0));}
};
MacResult compare_mac(uint32_t n,uint32_t side,uint32_t steps,uint32_t mode,uint64_t budget){
 if((n!=32 && n!=64 && n!=128) || (side!=8 && side!=16) || steps>8 || mode>3 || !budget || budget>1024ull*1024*1024)
  throw std::invalid_argument("MAC: resolution 32/64/128; side 8/16; steps 0..8; mode 0..3; budget <=1 GiB");
 MacResult r{};r.resolution=n;r.side=side;r.steps=steps;
 auto start=MClock::now();uint32_t grid=n/side;BrickTopology topology(grid*grid*grid);
 // Max speed < .55 voxels/step; RK2 and trilinear sampling require conservative support.
 // Two cells per step plus two initial cells cover component staggering and interpolation.
 int reach=int(steps)*2+2;
 int low=(mode==1 || mode==2)?0:std::max(0,int(n/4)-reach)/int(side);
 int high=(mode==1 || mode==2)?int(grid):(std::min(int(n),int(3*n/4)+reach)+int(side)-1)/int(side);
 topology.activate_box({low,low,low},{high-low,high-low,high-low});r.active_bricks=uint32_t(topology.active().size());
 std::vector<int32_t> map(grid*grid*grid,-1);std::vector<BrickCoord> coords(r.active_bricks);
 for(auto slot:topology.active()){auto c=topology.coord(slot);coords[slot]=c;map[(c.z*grid+c.y)*grid+c.x]=slot;}
 r.topology_ms=milliseconds(start);
 @autoreleasepool {
  id<MTLDevice> device=MTLCreateSystemDefaultDevice();if(!device)throw std::runtime_error("No Metal device available");
  NSError* error=nil;MTLCompileOptions* options=[MTLCompileOptions new];options.fastMathEnabled=NO;
  id<MTLLibrary> lib=[device newLibraryWithSource:[NSString stringWithUTF8String:mac_source] options:options error:&error];
  if(!lib)throw std::runtime_error(error.localizedDescription.UTF8String ?: "MAC shader compilation failed");
  id<MTLComputePipelineState> pipeline=[device newComputePipelineStateWithFunction:[lib newFunctionWithName:@"advect_mac"] error:&error];
  if(!pipeline)throw std::runtime_error(error.localizedDescription.UTF8String ?: "MAC pipeline failed");
  MP p{n,side,grid,1,0,r.active_bricks*(side+1)*side*side};MacEngine sparse(device,pipeline,p,map,coords,mode,budget);
  r.sparse_bytes=sparse.bytes;p.sparse=0;p.count=(n+1)*n*n;MacEngine dense(device,pipeline,p,{-1},{{0,0,0}},mode,budget);r.dense_bytes=dense.bytes;
  for(uint32_t i=0;i<steps;++i){
   if(i%2){start=MClock::now();r.dense_gpu_ms.push_back(dense.step());r.dense_wall_ms+=milliseconds(start);}
   start=MClock::now();r.sparse_gpu_ms.push_back(sparse.step());r.sparse_wall_ms+=milliseconds(start);
   if(!(i%2)){start=MClock::now();r.dense_gpu_ms.push_back(dense.step());r.dense_wall_ms+=milliseconds(start);}
  }
  auto* a=sparse.data();auto* b=dense.data();uint32_t per=(side+1)*side*side,sparse_count=r.active_bricks*per,dense_count=(n+1)*n*n;
  r.faces.resize(size_t(dense_count)*3);double square=0;
  for(uint32_t axis=0;axis<3;++axis){
   for(uint32_t i=0;i<sparse_count;++i){auto c=cell3(i%per,side,axis);auto brick=coords[i/per];int local[3]={c.x,c.y,c.z},bc[3]={brick.x,brick.y,brick.z};
    if(local[axis]==int(side) && bc[axis]!=int(grid)-1){++r.padding_faces;r.padding_error=std::max(r.padding_error,std::abs(double(a[axis*sparse_count+i])-12345.));}else ++r.owned_faces;}
   for(uint32_t i=0;i<dense_count;++i){auto c=cell3(i,n,axis);int v[3]={c.x,c.y,c.z},bc[3]={c.x/int(side),c.y/int(side),c.z/int(side)};bc[axis]=std::min(bc[axis],int(grid)-1);
    int slot=map[(bc[2]*grid+bc[1])*grid+bc[0]];float value=0;
    if(slot>=0)value=a[axis*sparse_count+uint32_t(slot)*per+index3(v[0]-bc[0]*side,v[1]-bc[1]*side,v[2]-bc[2]*side,side,axis)];
    auto offset=axis*dense_count+i;if(!std::isfinite(value) || !std::isfinite(b[offset]))throw std::runtime_error("Nonfinite MAC output");
    double e=std::abs(double(value)-b[offset]);square+=e*e;r.max_error=std::max(r.max_error,e);r.faces[offset]=value;
   }
  }
  r.rms_error=std::sqrt(square/(3.*dense_count));
 }
 return r;
}
}
