#include "projection.hpp"
#include "bricks.hpp"
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstring>
#include <memory>
namespace fluxfx {
static std::atomic<uint64_t> projection_bytes{0};
uint64_t projection_owned_bytes(){return projection_bytes.load();}
// Unit cells; pressure is impulse q=dt*p. Fixed solve mask, zero exterior q,
// Neumann outer walls. Velocity storage follows P1.5 canonical ownership.
static const char* source=R"METAL(
#include <metal_stdlib>
using namespace metal;
struct P {uint n,side,grid,sparse,cells,faces,axis,mode,step,schedule;};
uint3 shape(uint n,uint a){uint3 s(n);s[a]++;return s;}
bool inside(int3 c,uint n){return all(c>=0)&&all(c<int(n));}
bool solve(int3 c,constant P& p){
 if(!inside(c,p.n))return false;
 if(p.mode!=1 && p.mode!=2)return true;
 int lo=int(p.n/4),hi=int(3*p.n/4);
 if(p.mode==1)return all(c>=lo)&&all(c<hi);
 int e=int(p.n/4);return (all(c>=int(p.n/8))&&all(c<int(p.n/8)+e)) ||
 (all(c>=int(5*p.n/8))&&all(c<int(5*p.n/8)+e));
}
int cellIndex(int3 c,device const int* map,constant P& p){
 if(!inside(c,p.n))return -1;
 if(!p.sparse)return (c.z*p.n+c.y)*p.n+c.x;
 int3 b=c/int(p.side);int slot=map[(b.z*p.grid+b.y)*p.grid+b.x];if(slot<0)return -1;
 int3 l=c-b*int(p.side);return slot*p.side*p.side*p.side+(l.z*p.side+l.y)*p.side+l.x;
}
int3 cellCoord(uint i,device const packed_int3* coords,constant P& p){
 uint s=p.sparse?p.side:p.n,per=s*s*s;uint j=i%per;
 return int3(j%s,(j/s)%s,j/(s*s))+(p.sparse?int3(coords[i/per])*int(s):int3(0));
}
int faceIndex(int3 c,uint a,device const int* map,constant P& p){
 uint3 d=shape(p.n,a);if(any(c<0)||any(c>=int3(d)))return -1;
 if(!p.sparse)return a*p.faces+(c.z*d.y+c.y)*d.x+c.x;
 int3 b=c/int(p.side);b[a]=min(b[a],int(p.grid)-1);int slot=map[(b.z*p.grid+b.y)*p.grid+b.x];if(slot<0)return -1;
 int3 l=c-b*int(p.side);uint3 s=shape(p.side,a);
 return a*p.faces+slot*(p.side+1)*p.side*p.side+(l.z*s.y+l.y)*s.x+l.x;
}
float pressureAt(int3 c,device const float* q,device const int* map,constant P& p){
 if(!solve(c,p))return 0.;int i=cellIndex(c,map,p);return i<0?0.:q[i];
}
float faceAt(int3 c,uint a,device const float* u,device const int* map,constant P& p){
 int i=faceIndex(c,a,map,p);return i<0?0.:u[i];
}
kernel void divergence(device const float* u [[buffer(0)]],device float* out [[buffer(1)]],
 device const int* map [[buffer(2)]],device const packed_int3* coords [[buffer(3)]],constant P& p [[buffer(4)]],uint i [[thread_position_in_grid]]){
 if(i>=p.cells)return;int3 c=cellCoord(i,coords,p);float v=0.;
 if(solve(c,p))for(uint a=0;a<3;a++){int3 e(0);e[a]=1;v+=faceAt(c+e,a,u,map,p)-faceAt(c,a,u,map,p);}
 out[i]=v;
}
kernel void jacobi(device const float* old [[buffer(0)]],device float* out [[buffer(1)]],
 device const int* map [[buffer(2)]],device const packed_int3* coords [[buffer(3)]],constant P& p [[buffer(4)]],device const float* rhs [[buffer(5)]],uint i [[thread_position_in_grid]]){
 if(i>=p.cells)return;int3 c=cellCoord(i,coords,p);if(!solve(c,p)){out[i]=0.;return;}
 float sum=0.,diag=0.;
 for(uint a=0;a<3;a++)for(int sign=-1;sign<=1;sign+=2){int3 v=c;v[a]+=sign;
  if(inside(v,p.n)){diag+=1.;sum+=pressureAt(v,old,map,p);}}
 out[i]=mix(old[i],(sum-rhs[i])/diag,2.f/3.f);
}
kernel void gradient(device const float* u [[buffer(0)]],device float* out [[buffer(1)]],
 device const int* map [[buffer(2)]],device const packed_int3* coords [[buffer(3)]],constant P& p [[buffer(4)]],device const float* q [[buffer(5)]],uint i [[thread_position_in_grid]]){
 if(i>=p.faces)return;uint s=p.sparse?p.side:p.n,per=(s+1)*s*s,j=i%per;uint3 d=shape(s,p.axis);
 int3 l(j%d.x,(j/d.x)%d.y,j/(d.x*d.y)),b=p.sparse?int3(coords[i/per]):int3(0);
 if(p.sparse && l[p.axis]==int(s) && b[p.axis]!=int(p.grid)-1)return;
 int3 c=b*int(s)+l,e(0);e[p.axis]=1;float v=0.;
 if(c[p.axis]>0 && c[p.axis]<int(p.n) && (solve(c,p)||solve(c-e,p)))
  v=u[p.axis*p.faces+i]-(pressureAt(c,q,map,p)-pressureAt(c-e,q,map,p));
 out[p.axis*p.faces+i]=v;
}
// Coarse RHS stores 4*average(fine residual), accounting for doubled spacing.
kernel void residual(device const float* q [[buffer(0)]],device float* out [[buffer(1)]],
 device const int* map [[buffer(2)]],device const packed_int3* coords [[buffer(3)]],constant P& p [[buffer(4)]],device const float* rhs [[buffer(5)]],uint i [[thread_position_in_grid]]){
 if(i>=p.cells)return;int3 c=cellCoord(i,coords,p);if(!solve(c,p)){out[i]=0.;return;}
 float lap=0.;for(uint a=0;a<3;a++)for(int sign=-1;sign<=1;sign+=2){int3 v=c;v[a]+=sign;if(inside(v,p.n))lap+=pressureAt(v,q,map,p)-q[i];}
 out[i]=rhs[i]-lap;
}
kernel void restrictResidual(device const float* fine [[buffer(0)]],device float* coarse [[buffer(1)]],
 device const int* fineMap [[buffer(2)]],device const packed_int3* coarseCoords [[buffer(3)]],constant P& f [[buffer(4)]],constant P& c [[buffer(5)]],uint i [[thread_position_in_grid]]){
 if(i>=c.cells)return;int3 v=cellCoord(i,coarseCoords,c);float sum=0.;
 if(solve(v,c))for(int z=0;z<2;z++)for(int y=0;y<2;y++)for(int x=0;x<2;x++)sum+=pressureAt(2*v+int3(x,y,z),fine,fineMap,f);
 coarse[i]=sum*.5f;
}
kernel void prolongCorrection(device const float* coarse [[buffer(0)]],device float* fine [[buffer(1)]],
 device const int* coarseMap [[buffer(2)]],device const packed_int3* fineCoords [[buffer(3)]],constant P& f [[buffer(4)]],constant P& c [[buffer(5)]],uint i [[thread_position_in_grid]]){
 if(i>=f.cells)return;int3 v=cellCoord(i,fineCoords,f);if(!solve(v,f))return;
 float3 pos=(float3(v)+.5f)*.5f-.5f;int3 b=int3(floor(pos));float3 frac=pos-float3(b);float sum=0.;
 for(int z=0;z<2;z++)for(int y=0;y<2;y++)for(int x=0;x<2;x++){
  int3 q=clamp(b+int3(x,y,z),int3(0),int3(c.n)-1);float3 w=mix(1.f-frac,frac,float3(x,y,z));sum+=w.x*w.y*w.z*pressureAt(q,coarse,coarseMap,c);
 }
 fine[i]+=sum;
}
float3 faceOffset(uint a){float3 o(.5f);o[a]=0.f;return o;}
float sampleFaceField(float3 pos,uint a,device const float* u,device const int* map,constant P& p){
 float3 q=clamp(pos-faceOffset(a),float3(0),float3(shape(p.n,a)-1));int3 b=int3(floor(q));float3 f=q-float3(b);float v=0.;
 for(int z=0;z<2;z++)for(int y=0;y<2;y++)for(int x=0;x<2;x++){float3 w=mix(1.f-f,f,float3(x,y,z));v+=w.x*w.y*w.z*faceAt(b+int3(x,y,z),a,u,map,p);}return v;
}
float3 sampleVelocity(float3 pos,device const float* u,device const int* map,constant P& p){return float3(sampleFaceField(pos,0,u,map,p),sampleFaceField(pos,1,u,map,p),sampleFaceField(pos,2,u,map,p));}
kernel void transportVelocity(device const float* src [[buffer(0)]],device float* dst [[buffer(1)]],
 device const int* map [[buffer(2)]],device const packed_int3* coords [[buffer(3)]],constant P& p [[buffer(4)]],uint i [[thread_position_in_grid]]){
 if(i>=p.faces)return;uint s=p.sparse?p.side:p.n,per=(s+1)*s*s,j=i%per;uint3 d=shape(s,p.axis);
 int3 l(j%d.x,(j/d.x)%d.y,j/(d.x*d.y)),b=p.sparse?int3(coords[i/per]):int3(0);
 if(p.sparse && l[p.axis]==int(s) && b[p.axis]!=int(p.grid)-1)return;
 int3 c=b*int(s)+l,e(0);e[p.axis]=1;float value=0.;
 if(c[p.axis]>0 && c[p.axis]<int(p.n) && (solve(c,p)||solve(c-e,p))){
  float3 pos=float3(c)+faceOffset(p.axis),mid=pos-.5f*sampleVelocity(pos,src,map,p);
  value=sampleFaceField(pos-sampleVelocity(mid,src,map,p),p.axis,src,map,p);
 }dst[p.axis*p.faces+i]=value;
}
float emission(int3 c,constant P& p){
 float3 center=float3(.5f,.5f,.45f)*float(p.n);
 if(p.schedule==1)center.x+=.05f*float(p.n)*sin(.5f*float(p.step));
 float radius=float(p.n)/12.f;float3 d=(float3(c)+.5f-center)/radius;
 float rate=(p.schedule==2 && p.step%2)?0.f:.1f;
 return rate*max(0.f,1.f-dot(d,d));
}
kernel void injectDensity(device const float* src [[buffer(0)]],device float* dst [[buffer(1)]],
 device const int* map [[buffer(2)]],device const packed_int3* coords [[buffer(3)]],constant P& p [[buffer(4)]],uint i [[thread_position_in_grid]]){
 if(i>=p.cells)return;int3 c=cellCoord(i,coords,p);dst[i]=solve(c,p)?src[i]+emission(c,p):0.f;
}
// Conservative preflight: every possible nonzero destination and source brick.
// Full-domain scan is intentional in this correctness baseline.
kernel void requiredDensity(device const float* src [[buffer(0)]],device atomic_uint* flags [[buffer(1)]],
 device const int* map [[buffer(2)]],constant P& p [[buffer(4)]],device const float* u [[buffer(5)]],
 constant P& v [[buffer(6)]],device const int* velocityMap [[buffer(7)]],uint i [[thread_position_in_grid]]){
 if(i>=p.n*p.n*p.n)return;int3 c(i%p.n,(i/p.n)%p.n,i/(p.n*p.n));
 bool needed=emission(c,p)>0.f;
 float3 pos=float3(c)+.5f,mid=pos-.5f*sampleVelocity(pos,u,velocityMap,v);
 float3 q=clamp(pos-sampleVelocity(mid,u,velocityMap,v)-.5f,float3(0),float3(p.n-1));int3 b=int3(floor(q));
 for(int z=0;z<2;z++)for(int y=0;y<2;y++)for(int x=0;x<2;x++){
  int3 c0=clamp(b+int3(x,y,z),int3(0),int3(p.n-1));
  needed=needed || pressureAt(c0,src,map,p)>0.f || emission(c0,p)>0.f;
 }
 if(needed){int3 brick=c/int(p.side);atomic_store_explicit(flags+(brick.z*p.grid+brick.y)*p.grid+brick.x,1u,memory_order_relaxed);}
}
kernel void transportDensity(device const float* src [[buffer(0)]],device float* dst [[buffer(1)]],
 device const int* map [[buffer(2)]],device const packed_int3* coords [[buffer(3)]],constant P& p [[buffer(4)]],device const float* u [[buffer(5)]],constant P& v [[buffer(6)]],device const int* velocityMap [[buffer(7)]],uint i [[thread_position_in_grid]]){
 if(i>=p.cells)return;int3 c=cellCoord(i,coords,p);float value=0.;
 if(solve(c,p)){
  float3 pos=float3(c)+.5f,mid=pos-.5f*sampleVelocity(pos,u,velocityMap,v);
  float3 q=clamp(pos-sampleVelocity(mid,u,velocityMap,v)-.5f,float3(0),float3(p.n-1));int3 b=int3(floor(q));float3 f=q-float3(b);
  for(int z=0;z<2;z++)for(int y=0;y<2;y++)for(int x=0;x<2;x++){float3 w=mix(1.f-f,f,float3(x,y,z));value+=w.x*w.y*w.z*pressureAt(clamp(b+int3(x,y,z),int3(0),int3(p.n-1)),src,map,p);}
 }dst[i]=value;
}
)METAL";
struct PP {uint32_t n,side,grid,sparse,cells,faces,axis,mode,step,schedule;};
static bool solveCell(int x,int y,int z,uint32_t n,uint32_t mode){
 if(x<0||y<0||z<0||x>=int(n)||y>=int(n)||z>=int(n))return false;
 if(mode!=1 && mode!=2)return true;
 auto box=[&](int lo,int hi){return x>=lo&&y>=lo&&z>=lo&&x<hi&&y<hi&&z<hi;};
 return mode==1?box(n/4,3*n/4):(box(n/8,3*n/8)||box(5*n/8,7*n/8));
}
static float exactQ(int x,int y,int z,uint32_t n){
 const double k=8.*3.14159265358979323846/n;
 return float(std::cos(k*(x+.5))*std::cos(k*(y+.5))*std::cos(k*(z+.5)));
}
static float seed(int x,int y,int z,uint32_t a,uint32_t n,uint32_t mode){
 int c[3]={x,y,z},lo[3]={x,y,z};lo[a]--;
 if(c[a]==0||c[a]==int(n)||(!solveCell(x,y,z,n,mode)&&!solveCell(lo[0],lo[1],lo[2],n,mode))||mode==3)return 0.;
 if(mode==4)return exactQ(x,y,z,n)-exactQ(lo[0],lo[1],lo[2],n);
 float pos[3]={x+.5f,y+.5f,z+.5f};pos[a]-=.5f;
 return float(.2*(a+1)*std::sin(8.*3.14159265358979323846*pos[a]/n)+.1*std::cos(4.*3.14159265358979323846*pos[(a+1)%3]/n));
}
struct Engine {
 bool pooled=false;uint32_t densityCapacity=0,densityReallocations=0,densityReuses=0;uint64_t densityStorage=0,globalCopiedBytes=0;
 id<MTLBuffer> densityBuffer;
 bool adaptive=false;uint32_t expansions=0;uint64_t peakBytes=0,flagsOff=0,preservedBytes=0;double preflightMs=0.;
 std::vector<BrickCoord> densityCoords;
 PP p,densityP;std::vector<int32_t> densityMap;uint64_t densityMapoff=0,densityCoordoff=0,densityBytes=0;double densityTopologyMs=0.;
 id<MTLBuffer> buffer;id<MTLCommandQueue> queue;
 id<MTLComputePipelineState> div,relax,grad,residual,restriction,prolongation,transportVelocity,injectDensity,transportDensity,requiredDensity;
 uint64_t bytes=0,velocity=0,q0=0,q1=0,rhs=0,after=0,mapoff=0,coordoff=0,current=0,rho0=0,rho1=0;
 Engine(id<MTLDevice> device,id<MTLLibrary> lib,PP params,const std::vector<int32_t>& map,const std::vector<BrickCoord>& coords,uint64_t budget,bool coupled=false,uint32_t seedMode=UINT32_MAX,bool hybrid=false,bool adaptiveMode=false,bool pooledMode=false):pooled(pooledMode),adaptive(adaptiveMode),p(params),densityP(params){
  auto align=[](uint64_t v){return (v+255)&~uint64_t(255);};
  velocity=align(uint64_t(p.faces)*3*4);uint64_t scalar=align(uint64_t(p.cells)*4);
  q0=2*velocity;q1=q0+scalar;rhs=q1+scalar;after=rhs+scalar;mapoff=after+scalar;coordoff=mapoff+align(map.size()*4);bytes=coordoff+align(coords.size()*sizeof(BrickCoord));current=q0;
  densityMapoff=mapoff;densityCoordoff=coordoff;densityMap=map;
  auto densityTopologyStart=std::chrono::steady_clock::now();
  if(hybrid){
   densityP.sparse=1;densityP.mode=0;densityMap.assign(p.grid*p.grid*p.grid,-1);
   // Fixed diagnostic support: central half plus one brick on each side.
   for(uint32_t z=0;z<p.grid;z++)for(uint32_t y=0;y<p.grid;y++)for(uint32_t x=0;x<p.grid;x++){
    int lo=adaptive?int(p.n/2):int(p.n/4)-int(p.side),hi=adaptive?int(p.n/2)+1:int(3*p.n/4)+int(p.side);
    if(int((x+1)*p.side)<=lo||int(x*p.side)>=hi||int((y+1)*p.side)<=lo||int(y*p.side)>=hi||int((z+1)*p.side)<=lo||int(z*p.side)>=hi)continue;
    densityMap[(z*p.grid+y)*p.grid+x]=int(densityCoords.size());densityCoords.push_back({int(x),int(y),int(z)});
   }
   densityP.cells=uint32_t(densityCoords.size())*p.side*p.side*p.side;
   densityMapoff=bytes;densityCoordoff=bytes+align(densityMap.size()*4);bytes=densityCoordoff+align((adaptive?densityMap.size():densityCoords.size())*sizeof(BrickCoord));
   if(adaptive){flagsOff=bytes;bytes+=align(densityMap.size()*4);}
  }
  densityTopologyMs=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-densityTopologyStart).count();
  uint64_t densityScalar=align(uint64_t(densityP.cells)*4);rho0=bytes;rho1=rho0+densityScalar;
  if(coupled)bytes+=2*densityScalar;densityBytes=coupled?bytes-(coordoff+align(coords.size()*sizeof(BrickCoord))):0;
  if(pooled){
   densityCapacity=uint32_t(densityCoords.size());densityStorage=2*densityScalar;
   rho0=0;rho1=densityScalar;
  }
  peakBytes=bytes;
  if(bytes>budget||bytes>device.maxBufferLength)throw std::invalid_argument("Projection exceeds per-engine buffer budget");
  NSError* err=nil;
  div=[device newComputePipelineStateWithFunction:[lib newFunctionWithName:@"divergence"] error:&err];
  relax=[device newComputePipelineStateWithFunction:[lib newFunctionWithName:@"jacobi"] error:&err];
  grad=[device newComputePipelineStateWithFunction:[lib newFunctionWithName:@"gradient"] error:&err];
  residual=[device newComputePipelineStateWithFunction:[lib newFunctionWithName:@"residual"] error:&err];
  restriction=[device newComputePipelineStateWithFunction:[lib newFunctionWithName:@"restrictResidual"] error:&err];
  prolongation=[device newComputePipelineStateWithFunction:[lib newFunctionWithName:@"prolongCorrection"] error:&err];
  transportVelocity=[device newComputePipelineStateWithFunction:[lib newFunctionWithName:@"transportVelocity"] error:&err];
  injectDensity=[device newComputePipelineStateWithFunction:[lib newFunctionWithName:@"injectDensity"] error:&err];
  transportDensity=[device newComputePipelineStateWithFunction:[lib newFunctionWithName:@"transportDensity"] error:&err];
  requiredDensity=[device newComputePipelineStateWithFunction:[lib newFunctionWithName:@"requiredDensity"] error:&err];
  if(!requiredDensity||!div||!relax||!grad||!residual||!restriction||!prolongation||!transportVelocity||!injectDensity||!transportDensity)throw std::runtime_error(err.localizedDescription.UTF8String ?: "Projection pipeline failed");
  queue=[device newCommandQueue];if(!queue)throw std::runtime_error("Projection queue unavailable");
  buffer=[device newBufferWithLength:bytes-densityStorage options:MTLResourceStorageModeShared];if(!buffer)throw std::runtime_error("Projection allocation failed");
  if(pooled){densityBuffer=[device newBufferWithLength:densityStorage options:MTLResourceStorageModeShared];if(!densityBuffer)throw std::runtime_error("Density allocation failed");std::memset(densityBuffer.contents,0,densityStorage);}
  projection_bytes.fetch_add(bytes);auto* base=static_cast<char*>(buffer.contents);std::memset(base,0,bytes-densityStorage);
  std::memcpy(base+mapoff,map.data(),map.size()*4);std::memcpy(base+coordoff,coords.data(),coords.size()*sizeof(BrickCoord));
  if(hybrid){std::memcpy(base+densityMapoff,densityMap.data(),densityMap.size()*4);std::memcpy(base+densityCoordoff,densityCoords.data(),densityCoords.size()*sizeof(BrickCoord));}
  uint32_t s=p.sparse?p.side:p.n,per=(s+1)*s*s;
  for(uint32_t a=0;a<3;a++)for(uint32_t i=0;i<p.faces;i++){
   uint32_t j=i%per,sx=s+(a==0),sy=s+(a==1);int c[3]={int(j%sx),int((j/sx)%sy),int(j/(sx*sy))};auto b=p.sparse?coords[i/per]:BrickCoord{0,0,0};int bc[3]={b.x,b.y,b.z};
   bool padding=p.sparse&&c[a]==int(s)&&bc[a]!=int(p.grid)-1;
   for(int k=0;k<3;k++)c[k]+=bc[k]*s;
   data(0)[a*p.faces+i]=padding?12345.f:seed(c[0],c[1],c[2],a,p.n,seedMode==UINT32_MAX?p.mode:seedMode);
   data(velocity)[a*p.faces+i]=padding?12345.f:0.f;
  }
 }
 ~Engine(){if(buffer){densityBuffer=nil;buffer=nil;projection_bytes.fetch_sub(bytes);}}
 float* data(uint64_t offset){return reinterpret_cast<float*>(static_cast<char*>(buffer.contents)+offset);}
 float* densityData(uint64_t offset){return pooled?reinterpret_cast<float*>(static_cast<char*>(densityBuffer.contents)+offset):data(offset);}
 id<MTLBuffer> scalarBuffer(){return pooled?densityBuffer:buffer;}
 void dispatch(id<MTLCommandBuffer> cmd,id<MTLComputePipelineState> pipeline,uint64_t in,uint64_t out,uint64_t extra,uint32_t count){
  // Separate encoders ensure tracked-resource ordering between Jacobi iterations.
  auto enc=[cmd computeCommandEncoder];if(!enc)throw std::runtime_error("Projection encoder unavailable");
  [enc setComputePipelineState:pipeline];[enc setBuffer:buffer offset:in atIndex:0];[enc setBuffer:buffer offset:out atIndex:1];
  [enc setBuffer:buffer offset:mapoff atIndex:2];[enc setBuffer:buffer offset:coordoff atIndex:3];[enc setBytes:&p length:sizeof(p) atIndex:4];[enc setBuffer:buffer offset:extra atIndex:5];
  [enc setBytes:&p length:sizeof(p) atIndex:6];[enc setBuffer:buffer offset:mapoff atIndex:7];
  auto w=std::min<NSUInteger>(256,pipeline.maxTotalThreadsPerThreadgroup);
  [enc dispatchThreadgroups:MTLSizeMake((count+w-1)/w,1,1) threadsPerThreadgroup:MTLSizeMake(w,1,1)];[enc endEncoding];
 }
 void densityDispatch(id<MTLCommandBuffer> cmd,bool inject){
  densityP.step=p.step;densityP.schedule=p.schedule;
  auto enc=[cmd computeCommandEncoder];if(!enc)throw std::runtime_error("Density encoder unavailable");
  auto pipeline=inject?injectDensity:transportDensity;[enc setComputePipelineState:pipeline];
  [enc setBuffer:scalarBuffer() offset:inject?rho0:rho1 atIndex:0];[enc setBuffer:scalarBuffer() offset:inject?rho1:rho0 atIndex:1];
  [enc setBuffer:buffer offset:densityMapoff atIndex:2];[enc setBuffer:buffer offset:densityCoordoff atIndex:3];
  [enc setBytes:&densityP length:sizeof(densityP) atIndex:4];[enc setBuffer:buffer offset:velocity atIndex:5];
  [enc setBytes:&p length:sizeof(p) atIndex:6];[enc setBuffer:buffer offset:mapoff atIndex:7];
  auto w=std::min<NSUInteger>(256,pipeline.maxTotalThreadsPerThreadgroup);
  [enc dispatchThreadgroups:MTLSizeMake((densityP.cells+w-1)/w,1,1) threadsPerThreadgroup:MTLSizeMake(w,1,1)];[enc endEncoding];
 }
 double expandDensity(uint64_t budget){
  auto start=std::chrono::steady_clock::now();densityP.step=p.step;densityP.schedule=p.schedule;
  auto cmd=[queue commandBuffer];if(!cmd)throw std::runtime_error("Density preflight command unavailable");
  auto clear=[cmd blitCommandEncoder];if(!clear)throw std::runtime_error("Density preflight reset unavailable");[clear fillBuffer:buffer range:NSMakeRange(flagsOff,densityMap.size()*4) value:0];[clear endEncoding];
  auto enc=[cmd computeCommandEncoder];if(!enc)throw std::runtime_error("Density preflight encoder unavailable");[enc setComputePipelineState:requiredDensity];
  [enc setBuffer:scalarBuffer() offset:rho0 atIndex:0];[enc setBuffer:buffer offset:flagsOff atIndex:1];
  [enc setBuffer:buffer offset:densityMapoff atIndex:2];[enc setBytes:&densityP length:sizeof(densityP) atIndex:4];
  [enc setBuffer:buffer offset:velocity atIndex:5];[enc setBytes:&p length:sizeof(p) atIndex:6];[enc setBuffer:buffer offset:mapoff atIndex:7];
  auto w=std::min<NSUInteger>(256,requiredDensity.maxTotalThreadsPerThreadgroup);
  [enc dispatchThreadgroups:MTLSizeMake((p.n*p.n*p.n+w-1)/w,1,1) threadsPerThreadgroup:MTLSizeMake(w,1,1)];[enc endEncoding];
  [cmd commit];[cmd waitUntilCompleted];if(cmd.status!=MTLCommandBufferStatusCompleted)throw std::runtime_error("Density preflight failed");
  double gpu=cmd.GPUStartTime>0?(cmd.GPUEndTime-cmd.GPUStartTime)*1000:0.;
  auto nextMap=densityMap;auto nextCoords=densityCoords;auto flags=reinterpret_cast<uint32_t*>(data(flagsOff));
  for(uint32_t z=0;z<p.grid;z++)for(uint32_t y=0;y<p.grid;y++)for(uint32_t x=0;x<p.grid;x++){
   auto i=(z*p.grid+y)*p.grid+x;if(flags[i]&&nextMap[i]<0){nextMap[i]=int(nextCoords.size());nextCoords.push_back({int(x),int(y),int(z)});}
  }
  if(nextCoords.size()!=densityCoords.size()){
   if(pooled){
    if(nextCoords.size()>densityCapacity){
     uint32_t capacity=densityCapacity;while(capacity<nextCoords.size())capacity*=2;
     capacity=std::min<uint32_t>(capacity,uint32_t(densityMap.size()));
     uint64_t scalar=uint64_t(capacity)*p.side*p.side*p.side*4,newStorage=2*scalar;
     if(bytes+newStorage>budget||newStorage>buffer.device.maxBufferLength)throw std::invalid_argument("Density capacity growth exceeds transient buffer budget");
     auto replacement=[buffer.device newBufferWithLength:newStorage options:MTLResourceStorageModeShared];if(!replacement)throw std::runtime_error("Density capacity allocation failed");
     std::memset(replacement.contents,0,newStorage);projection_bytes.fetch_add(newStorage);
     try {
      auto copy=[queue commandBuffer];if(!copy)throw std::runtime_error("Density capacity copy unavailable");
      auto blit=[copy blitCommandEncoder];if(!blit)throw std::runtime_error("Density capacity encoder unavailable");
      uint64_t used=uint64_t(densityP.cells)*4;
      [blit copyFromBuffer:densityBuffer sourceOffset:0 toBuffer:replacement destinationOffset:0 size:used];[blit endEncoding];
      [copy commit];[copy waitUntilCompleted];if(copy.status!=MTLCommandBufferStatusCompleted)throw std::runtime_error("Density capacity copy failed");
      if(std::memcmp(replacement.contents,densityBuffer.contents,used)!=0)throw std::runtime_error("Density capacity preservation failed");
      preservedBytes+=used;if(copy.GPUStartTime>0)gpu+=(copy.GPUEndTime-copy.GPUStartTime)*1000;
     }catch(...){projection_bytes.fetch_sub(newStorage);throw;}
     peakBytes=std::max(peakBytes,bytes+newStorage);projection_bytes.fetch_sub(densityStorage);
     bytes+=newStorage-densityStorage;densityBytes+=newStorage-densityStorage;densityStorage=newStorage;
     densityBuffer=replacement;rho1=scalar;densityCapacity=capacity;densityReallocations++;
    }else densityReuses++;
    densityP.cells=uint32_t(nextCoords.size())*p.side*p.side*p.side;
   }else{
   uint64_t cells=nextCoords.size()*p.side*p.side*p.side,scalar=(cells*4+255)&~uint64_t(255),newBytes=rho0+2*scalar;
   // Both old and replacement allocations coexist while copying. Enforce peak.
   if(bytes+newBytes>budget||newBytes>buffer.device.maxBufferLength)throw std::invalid_argument("Adaptive density growth exceeds transient buffer budget");
   auto replacement=[buffer.device newBufferWithLength:newBytes options:MTLResourceStorageModeShared];if(!replacement)throw std::runtime_error("Density growth allocation failed");
   std::memset(replacement.contents,0,newBytes);projection_bytes.fetch_add(newBytes);
   try {
    auto copy=[queue commandBuffer];if(!copy)throw std::runtime_error("Density growth command unavailable");
    auto blit=[copy blitCommandEncoder];if(!blit)throw std::runtime_error("Density growth encoder unavailable");
    // Append-only brick IDs preserve the entire old scalar prefix exactly.
    [blit copyFromBuffer:buffer sourceOffset:0 toBuffer:replacement destinationOffset:0 size:rho0+uint64_t(densityP.cells)*4];[blit endEncoding];
    [copy commit];[copy waitUntilCompleted];if(copy.status!=MTLCommandBufferStatusCompleted)throw std::runtime_error("Density growth copy failed");
    if(std::memcmp(static_cast<char*>(replacement.contents)+rho0,data(rho0),uint64_t(densityP.cells)*4)!=0)throw std::runtime_error("Density preservation check failed");
    preservedBytes+=uint64_t(densityP.cells)*4;globalCopiedBytes+=rho0;
    if(copy.GPUStartTime>0)gpu+=(copy.GPUEndTime-copy.GPUStartTime)*1000;
   }catch(...){projection_bytes.fetch_sub(newBytes);throw;}
   peakBytes=std::max(peakBytes,bytes+newBytes);projection_bytes.fetch_sub(bytes);
   densityBytes+=newBytes-bytes;bytes=newBytes;buffer=replacement;rho1=rho0+scalar;densityP.cells=uint32_t(cells);
   }
   densityMap=std::move(nextMap);densityCoords=std::move(nextCoords);expansions++;
   std::memcpy(data(densityMapoff),densityMap.data(),densityMap.size()*4);std::memcpy(data(densityCoordoff),densityCoords.data(),densityCoords.size()*sizeof(BrickCoord));
  }
  preflightMs+=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();return gpu;
 }
 int densityIndex(uint32_t x,uint32_t y,uint32_t z){
  if(!densityP.sparse)return int((z*p.n+y)*p.n+x);
  int slot=densityMap[((z/p.side)*p.grid+y/p.side)*p.grid+x/p.side];
  return slot<0?-1:slot*p.side*p.side*p.side+((z%p.side)*p.side+y%p.side)*p.side+x%p.side;
 }
 void smooth(id<MTLCommandBuffer> cmd,uint32_t count){
  for(uint32_t i=0;i<count;i++){auto next=current==q0?q1:q0;dispatch(cmd,relax,current,next,rhs,p.cells);current=next;}
 }
 void transfer(id<MTLCommandBuffer> cmd,Engine& coarse,bool down){
  auto enc=[cmd computeCommandEncoder];if(!enc)throw std::runtime_error("Multigrid transfer encoder unavailable");
  auto pipeline=down?restriction:prolongation;[enc setComputePipelineState:pipeline];
  [enc setBuffer:down?buffer:coarse.buffer offset:down?after:coarse.current atIndex:0];
  [enc setBuffer:down?coarse.buffer:buffer offset:down?coarse.rhs:current atIndex:1];
  [enc setBuffer:down?buffer:coarse.buffer offset:down?mapoff:coarse.mapoff atIndex:2];
  [enc setBuffer:down?coarse.buffer:buffer offset:down?coarse.coordoff:coordoff atIndex:3];
  [enc setBytes:&p length:sizeof(p) atIndex:4];[enc setBytes:&coarse.p length:sizeof(p) atIndex:5];
  uint32_t count=down?coarse.p.cells:p.cells;auto w=std::min<NSUInteger>(256,pipeline.maxTotalThreadsPerThreadgroup);
  [enc dispatchThreadgroups:MTLSizeMake((count+w-1)/w,1,1) threadsPerThreadgroup:MTLSizeMake(w,1,1)];[enc endEncoding];
 }
 void cycle(id<MTLCommandBuffer> cmd,std::vector<std::unique_ptr<Engine>>& levels,size_t level){
  if(level==levels.size()){smooth(cmd,128);return;}
  smooth(cmd,4);dispatch(cmd,residual,current,after,rhs,p.cells);
  auto& coarse=*levels[level];
  auto blit=[cmd blitCommandEncoder];if(!blit)throw std::runtime_error("Multigrid reset encoder unavailable");
  [blit fillBuffer:coarse.buffer range:NSMakeRange(coarse.q0,coarse.rhs-coarse.q0) value:0];[blit endEncoding];coarse.current=coarse.q0;
  transfer(cmd,coarse,true);coarse.cycle(cmd,levels,level+1);transfer(cmd,coarse,false);smooth(cmd,4);
 }
 void copyVelocity(id<MTLCommandBuffer> cmd){
  auto enc=[cmd blitCommandEncoder];if(!enc)throw std::runtime_error("Coupled copy encoder unavailable");
  [enc copyFromBuffer:buffer sourceOffset:velocity toBuffer:buffer destinationOffset:0 size:velocity];[enc endEncoding];
 }
 double coupledRun(uint32_t steps,uint32_t cycles,uint32_t schedule,std::vector<std::unique_ptr<Engine>>& levels,uint64_t budget){
  double total=0.;p.schedule=schedule;
  for(uint32_t step=0;step<steps;step++){@autoreleasepool {
   p.step=step;auto cmd=[queue commandBuffer];if(!cmd)throw std::runtime_error("Coupled command unavailable");
   for(uint32_t a=0;a<3;a++){p.axis=a;dispatch(cmd,transportVelocity,0,velocity,0,p.faces);}copyVelocity(cmd);
   auto clear=[cmd blitCommandEncoder];if(!clear)throw std::runtime_error("Pressure clear encoder unavailable");
   [clear fillBuffer:buffer range:NSMakeRange(q0,rhs-q0) value:0];[clear endEncoding];current=q0;
   dispatch(cmd,div,0,rhs,0,p.cells);for(uint32_t c=0;c<cycles;c++)cycle(cmd,levels,0);
   for(uint32_t a=0;a<3;a++){p.axis=a;dispatch(cmd,grad,0,velocity,current,p.faces);}
   dispatch(cmd,div,velocity,after,0,p.cells);
   if(adaptive){
    [cmd commit];[cmd waitUntilCompleted];if(cmd.status!=MTLCommandBufferStatusCompleted)throw std::runtime_error("Adaptive projection failed");
    if(cmd.GPUStartTime>0)total+=(cmd.GPUEndTime-cmd.GPUStartTime)*1000;
    total+=expandDensity(budget);cmd=[queue commandBuffer];if(!cmd)throw std::runtime_error("Adaptive transport command unavailable");
   }
   densityDispatch(cmd,true);densityDispatch(cmd,false);
   copyVelocity(cmd);[cmd commit];[cmd waitUntilCompleted];
   if(cmd.status!=MTLCommandBufferStatusCompleted)throw std::runtime_error(cmd.error.localizedDescription.UTF8String ?: "Coupled dispatch failed");
   if(cmd.GPUStartTime>0)total+=(cmd.GPUEndTime-cmd.GPUStartTime)*1000;else total=-1.;
  }}return total;
 }
 double run(uint32_t iterations,uint32_t cycles,std::vector<std::unique_ptr<Engine>>& levels){@autoreleasepool {
  auto cmd=[queue commandBuffer];if(!cmd)throw std::runtime_error("Projection command unavailable");
  dispatch(cmd,div,0,rhs,0,p.cells);
  if(cycles){for(uint32_t i=0;i<cycles;i++)cycle(cmd,levels,0);}else smooth(cmd,iterations);
  for(uint32_t a=0;a<3;a++){p.axis=a;dispatch(cmd,grad,0,velocity,current,p.faces);}
  dispatch(cmd,div,velocity,after,0,p.cells);[cmd commit];[cmd waitUntilCompleted];
  if(cmd.status!=MTLCommandBufferStatusCompleted)throw std::runtime_error(cmd.error.localizedDescription.UTF8String ?: "Projection dispatch failed");
  return cmd.GPUStartTime>0?(cmd.GPUEndTime-cmd.GPUStartTime)*1000:-1.;
 }}
};
ProjectionResult compare_projection(uint32_t n,uint32_t side,uint32_t iterations,uint32_t mode,uint64_t budget,uint32_t cycles,uint32_t steps,uint32_t schedule,bool dense_full,bool global_support,bool hybrid,bool adaptive,bool pooled){
 if(pooled&&!adaptive)throw std::invalid_argument("Density capacity requires adaptive mode");
 if(adaptive&&!hybrid)throw std::invalid_argument("Adaptive requires hybrid");
 if(hybrid && (!global_support||!dense_full||!steps))throw std::invalid_argument("Hybrid requires global coupled comparison");
 if((n!=32&&n!=64&&n!=128)||(side!=8&&side!=16)||iterations>1024||cycles>16||steps>16||schedule>2||(steps&&!cycles)||mode>4||!budget||budget>1024ull*1024*1024)
  throw std::invalid_argument("Projection: n 32/64/128, brick 8/16, iterations 0..1024, mode 0..4, budget 1..1GiB");
 auto topologyStart=std::chrono::steady_clock::now();ProjectionResult r{};r.pooled=pooled;r.adaptive=adaptive;r.hybrid=hybrid;r.global_support=global_support;r.steps=steps;r.schedule=schedule;r.dense_full=dense_full;r.cycles=cycles;r.levels=1;r.resolution=n;r.side=side;r.iterations=iterations;r.mode=mode;uint32_t g=n/side;const uint32_t solveMode=global_support?0:mode;
 std::vector<int32_t> map(g*g*g,-1);std::vector<BrickCoord> coords;
 // Include a one-brick velocity halo so every solve face has its canonical owner.
 for(uint32_t bz=0;bz<g;bz++)for(uint32_t by=0;by<g;by++)for(uint32_t bx=0;bx<g;bx++){
  bool needed=false;
  for(int z=int(bz*side)-1;z<=int((bz+1)*side)&&!needed;z++)for(int y=int(by*side)-1;y<=int((by+1)*side)&&!needed;y++)for(int x=int(bx*side)-1;x<=int((bx+1)*side);x++)
   if(solveCell(x,y,z,n,solveMode)){needed=true;break;}
  if(needed){map[(bz*g+by)*g+bx]=int(coords.size());coords.push_back({int(bx),int(by),int(bz)});}
 }
 r.active_bricks=uint32_t(coords.size());r.topology_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-topologyStart).count();
 auto cellIndex=[&](uint32_t x,uint32_t y,uint32_t z){int slot=map[((z/side)*g+y/side)*g+x/side];return slot<0?-1:int(slot*side*side*side+((z%side)*side+y%side)*side+x%side);};
 @autoreleasepool {
  auto device=MTLCreateSystemDefaultDevice();if(!device)throw std::runtime_error("No Metal device");NSError* err=nil;auto opts=[MTLCompileOptions new];opts.fastMathEnabled=NO;
  auto lib=[device newLibraryWithSource:[NSString stringWithUTF8String:source] options:opts error:&err];if(!lib)throw std::runtime_error(err.localizedDescription.UTF8String ?: "Projection compile failed");
  PP p{n,side,g,1,r.active_bricks*side*side*side,r.active_bricks*(side+1)*side*side,0,solveMode};if(hybrid){p.sparse=0;p.cells=n*n*n;p.faces=(n+1)*n*n;}Engine sparse(device,lib,p,map,coords,budget,steps>0,mode,hybrid,adaptive,pooled);
  p.sparse=0;p.cells=n*n*n;p.faces=(n+1)*n*n;p.mode=dense_full?0:solveMode;Engine dense(device,lib,p,{-1},{{0,0,0}},budget,steps>0,mode);
  std::vector<std::unique_ptr<Engine>> sparseLevels,denseLevels;
  uint64_t sparseTotal=sparse.bytes,denseTotal=dense.bytes;
  if(cycles)for(uint32_t cn=n/2;cn>=8;cn/=2){
   uint32_t cs=std::min(side,cn),cg=cn/cs;std::vector<int32_t> cm(cg*cg*cg,-1);std::vector<BrickCoord> cc;
   for(uint32_t z=0;z<cg;z++)for(uint32_t y=0;y<cg;y++)for(uint32_t x=0;x<cg;x++){
    bool active=false;for(uint32_t k=0;k<cs&&!active;k++)for(uint32_t j=0;j<cs&&!active;j++)for(uint32_t i=0;i<cs;i++)if(solveCell(x*cs+i,y*cs+j,z*cs+k,cn,solveMode)){active=true;break;}
    if(active){cm[(z*cg+y)*cg+x]=int(cc.size());cc.push_back({int(x),int(y),int(z)});}
   }
   PP cp{cn,cs,cg,hybrid?0u:1u,uint32_t(cc.size())*cs*cs*cs,0,0,solveMode};
   if(sparseTotal>=budget||denseTotal>=budget)throw std::invalid_argument("Multigrid hierarchy exceeds per-engine budget");
   sparseLevels.push_back(std::make_unique<Engine>(device,lib,cp,cm,cc,budget-sparseTotal));sparseTotal+=sparseLevels.back()->bytes;
   cp.sparse=0;cp.cells=cn*cn*cn;cp.mode=dense_full?0:solveMode;denseLevels.push_back(std::make_unique<Engine>(device,lib,cp,std::vector<int32_t>{-1},std::vector<BrickCoord>{{0,0,0}},budget-denseTotal));denseTotal+=denseLevels.back()->bytes;
  }
  r.levels=uint32_t(sparseLevels.size())+1;r.sparse_hierarchy_bytes=sparseTotal-sparse.bytes;r.dense_hierarchy_bytes=denseTotal-dense.bytes;
  r.sparse_bytes=sparseTotal;r.dense_bytes=denseTotal;r.density_cells=sparse.densityP.cells;r.density_bytes=sparse.densityBytes;r.density_bricks=sparse.densityP.cells/(side*side*side);r.density_topology_ms=sparse.densityTopologyMs;
  auto t=std::chrono::steady_clock::now();r.sparse_gpu_ms=steps?sparse.coupledRun(steps,cycles,schedule,sparseLevels,budget-r.sparse_hierarchy_bytes):sparse.run(iterations,cycles,sparseLevels);r.sparse_wall_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-t).count();
  t=std::chrono::steady_clock::now();r.dense_gpu_ms=steps?dense.coupledRun(steps,cycles,schedule,denseLevels,budget-r.dense_hierarchy_bytes):dense.run(iterations,cycles,denseLevels);r.dense_wall_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-t).count();
  r.sparse_bytes=sparse.bytes+r.sparse_hierarchy_bytes;r.density_bytes=sparse.densityBytes;r.density_cells=sparse.densityP.cells;r.density_bricks=r.density_cells/(side*side*side);
  r.global_copy_bytes=sparse.globalCopiedBytes;r.density_capacity=sparse.densityCapacity;r.density_reallocations=sparse.densityReallocations;r.density_reuses=sparse.densityReuses;r.preserved_bytes=sparse.preservedBytes;r.expansions=sparse.expansions;r.peak_sparse_bytes=sparse.peakBytes+r.sparse_hierarchy_bytes;r.preflight_ms=sparse.preflightMs;
  if(steps)r.density.resize(n*n*n);r.pressure.resize(n*n*n);r.before.resize(n*n*n);r.after.resize(n*n*n);double before2=0,after2=0,res2=0,denseAfter2=0;uint32_t denseCells=0;
  for(uint32_t z=0;z<n;z++)for(uint32_t y=0;y<n;y++)for(uint32_t x=0;x<n;x++){
   uint32_t i=(z*n+y)*n+x;int s=hybrid?int(i):cellIndex(x,y,z);
   r.pressure[i]=s<0?0:sparse.data(sparse.current)[s];r.before[i]=s<0?0:sparse.data(sparse.rhs)[s];r.after[i]=s<0?0:sparse.data(sparse.after)[s];
   r.divergence_error=std::max(r.divergence_error,std::abs(double(r.after[i])-dense.data(dense.after)[i]));
   if(solveCell(x,y,z,n,dense_full?0:solveMode)){double v=dense.data(dense.after)[i];denseAfter2+=v*v;denseCells++;}
   if(steps){
    int di=sparse.densityIndex(x,y,z);float value=di<0?0:sparse.densityData(sparse.rho0)[di],other=dense.densityData(dense.rho0)[i];
    if(!std::isfinite(value)||!std::isfinite(other)||value<0||other<0)throw std::runtime_error("Invalid coupled density");
    r.density[i]=value;r.density_error=std::max(r.density_error,std::abs(double(value)-other));r.sparse_mass+=value;r.dense_mass+=other;
    if(solveCell(x,y,z,n,solveMode))for(uint32_t step=0;step<steps;step++){
     if(schedule==2 && step%2)continue;
     double cx=.5*n+(schedule==1?.05*n*std::sin(.5*step):0.),radius=double(n)/12;
     double dx=(x+.5-cx)/radius,dy=(y+.5-.5*n)/radius,dz=(z+.5-.45*n)/radius;
     r.injected_mass+=.1*std::max(0.,1.-dx*dx-dy*dy-dz*dz);
    }
   }
   r.pressure_error=std::max(r.pressure_error,std::abs(double(r.pressure[i])-dense.data(dense.current)[i]));
   if(!std::isfinite(r.pressure[i])||!std::isfinite(r.after[i]))throw std::runtime_error("Nonfinite projection output");
   if(solveCell(x,y,z,n,solveMode)){r.solve_cells++;before2+=double(r.before[i])*r.before[i];after2+=double(r.after[i])*r.after[i];}
  }
  // Independent host residual from exported canonical q, not the divergence kernel.
  for(uint32_t z=0;z<n;z++)for(uint32_t y=0;y<n;y++)for(uint32_t x=0;x<n;x++)if(solveCell(x,y,z,n,solveMode)){
   int c[3]={int(x),int(y),int(z)};uint32_t i=(z*n+y)*n+x;double lap=0;
   for(int a=0;a<3;a++)for(int sign:{-1,1}){int v[3]={c[0],c[1],c[2]};v[a]+=sign;if(v[a]>=0&&v[a]<int(n))lap+=r.pressure[(v[2]*n+v[1])*n+v[0]]-r.pressure[i];}
   double residual=r.before[i]-lap;res2+=residual*residual;
  }
  r.dense_after_rms=std::sqrt(denseAfter2/denseCells);r.before_rms=std::sqrt(before2/r.solve_cells);r.after_rms=std::sqrt(after2/r.solve_cells);r.residual_rms=std::sqrt(res2/r.solve_cells);
  uint32_t dc=(n+1)*n*n,sc=sparse.p.faces,per=(side+1)*side*side;r.faces.resize(3*dc);
  for(uint32_t a=0;a<3;a++){
   for(uint32_t i=0;!hybrid&&i<sc;i++){uint32_t j=i%per,sx=side+(a==0),sy=side+(a==1);int l[3]={int(j%sx),int((j/sx)%sy),int(j/(sx*sy))};auto b=coords[i/per];int bc[3]={b.x,b.y,b.z};if(l[a]==int(side)&&bc[a]!=int(g)-1)r.padding_error=std::max(r.padding_error,std::abs(double(sparse.data(sparse.velocity)[a*sc+i])-12345.));}
   for(uint32_t i=0;i<dc;i++){
    uint32_t sx=n+(a==0),sy=n+(a==1);int c[3]={int(i%sx),int((i/sx)%sy),int(i/(sx*sy))},b[3]={c[0]/int(side),c[1]/int(side),c[2]/int(side)};b[a]=std::min(b[a],int(g)-1);
    int slot=map[(b[2]*g+b[1])*g+b[0]],l[3]={c[0]-b[0]*int(side),c[1]-b[1]*int(side),c[2]-b[2]*int(side)};float v=hybrid?sparse.data(sparse.velocity)[a*dc+i]:slot<0?0:sparse.data(sparse.velocity)[a*sc+slot*per+(l[2]*(side+(a==1))+l[1])*(side+(a==0))+l[0]];
    if(!std::isfinite(v))throw std::runtime_error("Nonfinite projected face");r.faces[a*dc+i]=v;r.max_error=std::max(r.max_error,std::abs(double(v)-dense.data(dense.velocity)[a*dc+i]));if(c[a]==0||c[a]==int(n))r.wall_error=std::max(r.wall_error,std::abs(double(v)));
   }
  }
 }
 return r;
}
}
