#include "arena.hpp"
#include <cassert>
#include <iostream>
#include <random>
int main() {
    using namespace fluxfx;
    Arena a(1024);
    auto x=a.allocate(1),y=a.allocate(257),z=a.allocate(256);
    assert(a.used==1024 && a.get(y).offset==256 && a.get(y).bytes==512);
    try {a.allocate(1);assert(false);} catch(const std::runtime_error&) {}
    a.release(y);
    auto fresh=a.allocate(500);assert(fresh!=y && a.get(fresh).offset==256);
    try {a.get(y);assert(false);} catch(const std::invalid_argument&) {}
    a.release(x);a.release(z);a.release(fresh);assert(a.used==0 && a.largest_free()==1024);
    Arena other(1024);auto foreign=other.allocate(1);
    try {a.release(foreign);assert(false);} catch(const std::invalid_argument&) {}
    std::mt19937 rng(110);std::vector<uint64_t> ids;
    Arena stress(65536);
    for(int i=0;i<10000;++i) {
        if(!ids.empty() && rng()%2) {
            auto index=rng()%ids.size();stress.release(ids[index]);ids.erase(ids.begin()+index);
        } else {
            try { ids.push_back(stress.allocate(1+rng()%2048)); } catch(const std::runtime_error&) {}
        }
        uint64_t sum=0;
        for(auto first:ids) {
            auto s=stress.get(first);sum+=s.bytes;assert(s.offset%256==0 && s.offset+s.bytes<=65536);
            for(auto second:ids) if(first!=second) {
                auto t=stress.get(second);assert(s.offset+s.bytes<=t.offset || t.offset+t.bytes<=s.offset);
            }
        }
        assert(sum==stress.used && stress.used<=65536);
    }
    for(auto id:ids)stress.release(id);
    assert(stress.largest_free()==65536);
    std::cout<<"Arena alignment, budget, reuse, stale/foreign handles, coalescing and 10000 randomized operations PASS\n";
}
