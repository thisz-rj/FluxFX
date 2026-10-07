#pragma once
#include "bricks.hpp"
#include <cmath>
#include <algorithm>
namespace fluxfx {
struct RegionSource { double x,y,z,radius,vx,vy,vz; };
class RegionTracker {
    std::vector<uint8_t> wanted_;
    std::vector<uint32_t> ages_;
public:
    explicit RegionTracker(uint32_t capacity):wanted_(64*64*64),ages_(capacity,0) {}
    uint32_t age(uint32_t slot) const {return ages_.at(slot);}
    uint64_t bytes() const {return wanted_.capacity()+ages_.capacity()*sizeof(uint32_t);}
    void update(BrickTopology& topology,const std::vector<RegionSource>& sources,
                uint32_t grid,double dt,uint32_t linger,uint32_t halo) {
        if(!grid || grid>64 || !std::isfinite(dt) || dt<=0 || dt>1 || !linger || linger>1000 || halo>4 || sources.size()>64)
            throw std::invalid_argument("Region settings: grid 1..64, dt (0,1], linger 1..1000, halo 0..4, sources <=64");
        std::fill(wanted_.begin(),wanted_.end(),0);
        uint32_t count=0;
        for(auto s:sources) {
            for(double v:{s.x,s.y,s.z,s.radius,s.vx,s.vy,s.vz})
                if(!std::isfinite(v) || std::abs(v)>1000000)throw std::invalid_argument("Region source must be finite and bounded");
            if(s.radius<0)throw std::invalid_argument("Source radius must be nonnegative");
            double c[3]={s.x,s.y,s.z},v[3]={s.vx,s.vy,s.vz};int lo[3],hi[3];
            for(int d=0;d<3;++d) {
                double end=c[d]+v[d]*dt;
                lo[d]=int(std::floor(std::clamp((std::min(c[d],end)-s.radius)*grid-double(halo),0.,double(grid))));
                hi[d]=int(std::ceil(std::clamp((std::max(c[d],end)+s.radius)*grid+double(halo),0.,double(grid))));
            }
            for(int z=lo[2];z<hi[2];++z)for(int y=lo[1];y<hi[1];++y)for(int x=lo[0];x<hi[0];++x) {
                auto i=(z*grid+y)*grid+x;if(!wanted_[i]){wanted_[i]=1;++count;}
            }
        }
        auto desired=[&](BrickCoord c) {
            return c.x>=0 && c.y>=0 && c.z>=0 && c.x<int(grid) && c.y<int(grid) && c.z<int(grid)
                && wanted_[(c.z*grid+c.y)*grid+c.x];
        };
        uint32_t retained=0;
        for(auto slot:topology.active())if(!desired(topology.coord(slot)) && ages_[slot]+1<linger)++retained;
        if(uint64_t(count)+retained>topology.capacity())throw std::runtime_error("Active region plus retained bricks exceeds pool capacity; increase pool or reduce halo");
        // No mutation, including age advancement, before capacity preflight succeeds.
        size_t i=0;
        while(i<topology.active().size()) {
            auto slot=topology.active()[i];auto c=topology.coord(slot);
            if(desired(c)){ages_[slot]=0;++i;}
            else if(++ages_[slot]>=linger)topology.deactivate(c);
            else ++i;
        }
        for(uint32_t z=0;z<grid;++z)for(uint32_t y=0;y<grid;++y)for(uint32_t x=0;x<grid;++x)
            if(wanted_[(z*grid+y)*grid+x])ages_[topology.activate({int(x),int(y),int(z)})]=0;
    }
};
}
