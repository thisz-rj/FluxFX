#include "regions.hpp"
#include <cassert>
#include <iostream>
using namespace fluxfx;
int main(){
 BrickTopology t(64);RegionTracker r(64);
 RegionSource a{.3,.3,.3,.01,0,0,0};
 r.update(t,{a},8,.1,3,0);assert(t.active().size()==1 && t.lookup({2,2,2})>=0);
 auto slot=t.active()[0];r.update(t,{},8,.1,3,0);assert(r.age(slot)==1);
 r.update(t,{},8,.1,3,0);assert(r.age(slot)==2 && t.active().size()==1);
 r.update(t,{},8,.1,3,0);assert(t.active().empty());
 a.vx=3;r.update(t,{a},8,.1,3,0);assert(t.lookup({4,2,2})>=0 && t.lookup({1,2,2})<0);
 auto before=t.active();
 try{r.update(t,{{.5,.5,.5,2,0,0,0}},8,.1,3,0);assert(false);}catch(const std::runtime_error&){}
 assert(before==t.active());for(auto s:before)assert(r.age(s)==0);
 r.update(t,{},8,.1,1,0);assert(t.active().empty());
 r.update(t,{{0,0,0,.01,0,0,0}},8,.1,3,1);assert(t.active().size()==8);
 r.update(t,{{-2,-2,-2,.01,0,0,0}},8,.1,1,0);assert(t.active().empty());
 r.update(t,{a,a},8,.1,3,0);assert(t.active().size()==3);
 for(int i=0;i<2000;++i){r.update(t,{a},8,.1,3,0);r.update(t,{},8,.1,3,0);}
 assert(t.active().size()==3);for(auto s:t.active())assert(r.age(s)==1);
 std::cout<<"PASS: source activation, directional prediction, halo clipping, hysteresis, atomic capacity failure, duplicates, 4000 updates\n";
}
