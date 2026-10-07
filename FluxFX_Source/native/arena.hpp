#pragma once
#include <algorithm>
#include <atomic>
#include <cstdint>
#include <map>
#include <stdexcept>
#include <vector>

namespace fluxfx {
struct Span { uint64_t offset, bytes, requested; };
// GPU-independent suballocator. IDs are never reused, including across arenas.
class Arena {
    inline static std::atomic<uint64_t> next_id{1};
    uint64_t capacity_;
    std::vector<Span> free_;
    std::map<uint64_t,Span> live_;
public:
    uint64_t used=0, peak=0, allocations=0;
    explicit Arena(uint64_t capacity):capacity_(capacity),free_{{0,capacity,capacity}} {
        if (!capacity || capacity%256) throw std::invalid_argument("Arena capacity must be a positive multiple of 256");
    }
    uint64_t allocate(uint64_t bytes) {
        if (!bytes || bytes>capacity_) throw std::invalid_argument("Allocation is empty or exceeds arena budget");
        if (live_.size()>=65536) throw std::runtime_error("Arena allocation handle limit reached");
        uint64_t aligned=(bytes+255)&~uint64_t(255);
        for (size_t i=0;i<free_.size();++i) if (free_[i].bytes>=aligned) {
            uint64_t id=next_id.fetch_add(1);
            if (!id) throw std::runtime_error("Allocation ID exhausted");
            Span span{free_[i].offset,aligned,bytes};
            live_.emplace(id,span);
            free_[i].offset+=aligned;free_[i].bytes-=aligned;
            if (!free_[i].bytes) free_.erase(free_.begin()+i);
            used+=aligned;peak=std::max(peak,used);++allocations;
            return id;
        }
        throw std::runtime_error("Arena budget exhausted or fragmented; free allocations first");
    }
    const Span& get(uint64_t id) const {
        auto it=live_.find(id);
        if (it==live_.end()) throw std::invalid_argument("Unknown, freed or foreign allocation handle");
        return it->second;
    }
    void release(uint64_t id) {
        Span span=get(id);
        auto merged=free_;merged.push_back(span);
        std::sort(merged.begin(),merged.end(),[](Span a,Span b){return a.offset<b.offset;});
        std::vector<Span> compact;
        for (auto item:merged) {
            if (!compact.empty() && compact.back().offset+compact.back().bytes==item.offset)
                compact.back().bytes+=item.bytes;
            else compact.push_back(item);
        }
        free_.swap(compact);live_.erase(id);used-=span.bytes;
    }
    uint64_t largest_free() const { uint64_t n=0;for(auto s:free_) n=std::max(n,s.bytes);return n; }
    uint64_t count() const { return live_.size(); }
};
}
