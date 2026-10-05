#include "bricks.hpp"
#include <cassert>
#include <map>
#include <random>
#include <tuple>
#include <iostream>
using namespace fluxfx;
int main() {
    BrickTopology t(64);
    auto center=t.activate({0,0,0});assert(center==t.activate({0,0,0}));
    auto east=t.activate({1,0,0});assert(t.neighbors({0,0,0})[1]==int(east));
    assert(t.neighbors({1,0,0})[0]==int(center));
    t.deactivate({1,0,0});assert(t.neighbors({0,0,0})[1]==-1);
    assert(t.activate({-1,0,0})==east);
    t.activate({1048575,-1048576,0});assert(t.neighbors({1048575,-1048576,0})[1]==-1);
    t.deactivate({1048575,-1048576,0});t.deactivate({-1,0,0});t.deactivate({0,0,0});
    auto bytes=t.metadata_bytes();
    std::map<std::tuple<int,int,int>,uint32_t> reference;
    std::mt19937 rng(78);
    for(int k=0;k<20000;++k) {
        BrickCoord c{int(rng()%8)-4,int(rng()%8)-4,int(rng()%8)-4};
        auto key=std::make_tuple(c.x,c.y,c.z);
        if(rng()%2) {
            if(reference.size()<64 || reference.count(key))reference[key]=t.activate(c);
            else {try{t.activate(c);assert(false);}catch(const std::runtime_error&) {}}
        } else {bool was=reference.erase(key);assert(t.deactivate(c)==was);}
        assert(t.active().size()==reference.size());assert(t.metadata_bytes()==bytes);
        for(auto item:reference) {
            auto [x,y,z]=item.first;assert(t.lookup({x,y,z})==int(item.second));
            auto neighbors=t.neighbors({x,y,z});
            std::array<BrickCoord,6> adjacent={{{x-1,y,z},{x+1,y,z},{x,y-1,z},{x,y+1,z},{x,y,z-1},{x,y,z+1}}};
            for(int d=0;d<6;++d) {
                auto a=adjacent[d];auto it=reference.find({a.x,a.y,a.z});
                assert(neighbors[d]==(it==reference.end()?-1:int(it->second)));
            }
        }
    }
    BrickTopology box(8);box.activate_box({0,0,0},{2,2,2});
    assert(box.active().size()==8);
    try{box.activate_box({1,0,0},{2,2,2});assert(false);}catch(const std::runtime_error&){}
    assert(box.active().size()==8 && box.lookup({2,0,0})==-1);
    std::cout<<"PASS: 20000 randomized topology operations, neighbors, fixed storage, exhaustion and atomic box preflight\n";
}
