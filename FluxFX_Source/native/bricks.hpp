#pragma once
#include <array>
#include <cstdint>
#include <stdexcept>
#include <vector>

namespace fluxfx {
struct BrickCoord {
    int32_t x,y,z;
    bool operator==(const BrickCoord& c) const { return x==c.x && y==c.y && z==c.z; }
};
// Fixed-capacity CPU topology. All storage is reserved at construction.
// Slots remain stable until their coordinate is deactivated; they are not handles.
class BrickTopology {
    struct Entry { BrickCoord coord{}; int32_t slot=-1; }; // -1 empty, -2 tombstone
    std::vector<Entry> table_;
    std::vector<BrickCoord> coords_;
    std::vector<uint32_t> positions_,free_,active_;
    static uint64_t hash(BrickCoord c) {
        uint64_t v=uint32_t(c.x)*0x9e3779b185ebca87ull;
        v^=uint32_t(c.y)*0xc2b2ae3d27d4eb4full;
        v^=uint32_t(c.z)*0x165667b19e3779f9ull;
        v^=v>>33;v*=0xff51afd7ed558ccdull;return v^(v>>33);
    }
    size_t find(BrickCoord c) const {
        const size_t mask=table_.size()-1;size_t pos=hash(c)&mask;
        for(size_t n=0;n<table_.size();++n,pos=(pos+1)&mask) {
            const auto& e=table_[pos];
            if(e.slot==-1 || (e.slot>=0 && e.coord==c)) return pos;
        }
        return table_.size();
    }
public:
    explicit BrickTopology(uint32_t capacity) {
        if(!capacity || capacity>262144) throw std::invalid_argument("Brick capacity must be 1..262144");
        size_t n=2;while(n<size_t(capacity)*2)n*=2;
        table_.resize(n);coords_.resize(capacity);positions_.resize(capacity);
        free_.reserve(capacity);active_.reserve(capacity);
        for(uint32_t i=capacity;i>0;--i)free_.push_back(i-1);
    }
    static void validate(BrickCoord c) {
        for(int32_t v:{c.x,c.y,c.z}) if(v < -1048576 || v > 1048575)
            throw std::invalid_argument("Brick coordinates must be in [-1048576,1048575]");
    }
    int32_t lookup(BrickCoord c) const {
        validate(c);auto i=find(c);return i<table_.size() && table_[i].slot>=0?table_[i].slot:-1;
    }
    uint32_t activate(BrickCoord c) {
        validate(c);int32_t prior=lookup(c);if(prior>=0)return uint32_t(prior);
        if(free_.empty())throw std::runtime_error("Brick pool capacity exhausted");
        size_t pos=hash(c)&(table_.size()-1);
        while(table_[pos].slot>=0)pos=(pos+1)&(table_.size()-1);
        uint32_t slot=free_.back();free_.pop_back();
        table_[pos]={c,int32_t(slot)};coords_[slot]=c;
        positions_[slot]=uint32_t(active_.size());active_.push_back(slot);return slot;
    }
    bool deactivate(BrickCoord c) {
        validate(c);auto i=find(c);if(i==table_.size() || table_[i].slot<0)return false;
        uint32_t slot=uint32_t(table_[i].slot),pos=positions_[slot],last=active_.back();
        active_[pos]=last;positions_[last]=pos;active_.pop_back();
        table_[i].slot=-2;free_.push_back(slot);return true;
    }
    std::array<int32_t,6> neighbors(BrickCoord c) const {
        validate(c);
        std::array<BrickCoord,6> adjacent={{{c.x-1,c.y,c.z},{c.x+1,c.y,c.z},
            {c.x,c.y-1,c.z},{c.x,c.y+1,c.z},{c.x,c.y,c.z-1},{c.x,c.y,c.z+1}}};
        std::array<int32_t,6> result{};
        for(size_t i=0;i<6;++i) {
            auto p=find(adjacent[i]);result[i]=p<table_.size() && table_[p].slot>=0?table_[p].slot:-1;
        }
        return result;
    }
    const std::vector<uint32_t>& active() const {return active_;}
    BrickCoord coord(uint32_t slot) const {return coords_.at(slot);}
    uint32_t capacity() const {return uint32_t(coords_.size());}
    uint64_t metadata_bytes() const {
        return table_.capacity()*sizeof(Entry)+coords_.capacity()*sizeof(BrickCoord)+
            (positions_.capacity()+free_.capacity()+active_.capacity())*sizeof(uint32_t);
    }
    // Validate and preflight before mutation, including capacity exhaustion.
    void activate_box(BrickCoord lo,BrickCoord extent) {
        validate(lo);
        if(extent.x<1 || extent.y<1 || extent.z<1 || extent.x>4096 || extent.y>4096 || extent.z>4096)
            throw std::invalid_argument("Box extent must be 1..4096 per axis");
        validate({lo.x+extent.x-1,lo.y+extent.y-1,lo.z+extent.z-1});
        if(uint64_t(extent.x)*extent.y*extent.z>capacity())throw std::runtime_error("Box exceeds pool capacity");
        uint32_t needed=0;
        for(int z=0;z<extent.z;++z)for(int y=0;y<extent.y;++y)for(int x=0;x<extent.x;++x)
            needed+=lookup({lo.x+x,lo.y+y,lo.z+z})<0;
        if(needed>free_.size())throw std::runtime_error("Brick pool capacity exhausted");
        for(int z=0;z<extent.z;++z)for(int y=0;y<extent.y;++y)for(int x=0;x<extent.x;++x)
            activate({lo.x+x,lo.y+y,lo.z+z});
    }
};
}
