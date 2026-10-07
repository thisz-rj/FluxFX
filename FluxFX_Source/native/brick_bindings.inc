// Included after the shared exception/integer helpers in module.cpp.
static constexpr const char* brick_name="fluxfx_core.BrickPool";
static fluxfx::BrickPool* get_bricks(PyObject* obj) {
    return static_cast<fluxfx::BrickPool*>(PyCapsule_GetPointer(obj,brick_name));
}
static void destroy_bricks(PyObject* obj) {
    auto* pool=get_bricks(obj);if(pool)delete pool;else PyErr_Clear();
}
static PyObject* brick_create(PyObject*,PyObject* args) {
    PyObject *s,*c,*b;uint64_t side,capacity,budget;
    if(!PyArg_ParseTuple(args,"OOO",&s,&c,&b) || !integer(s,side) || !integer(c,capacity) || !integer(b,budget))return nullptr;
    if((side!=8 && side!=16) || !capacity || capacity>262144) {
        PyErr_SetString(PyExc_ValueError,"side: 8 or 16; capacity: 1..262144");return nullptr;
    }
    try {
        auto pool=std::make_unique<fluxfx::BrickPool>(uint32_t(side),uint32_t(capacity),budget);
        auto* capsule=PyCapsule_New(pool.get(),brick_name,destroy_bricks);
        if(capsule)pool.release();return capsule;
    } catch(...) {return cpp_error();}
}
static PyObject* brick_close(PyObject*,PyObject* obj) {
    auto* p=get_bricks(obj);if(!p)return nullptr;
    try {p->close();Py_RETURN_NONE;}catch(...){return cpp_error();}
}
static PyObject* brick_command(PyObject*,PyObject* args) {
    PyObject* obj;const char* action;int x,y,z;
    if(!PyArg_ParseTuple(args,"Osiii",&obj,&action,&x,&y,&z))return nullptr;
    auto* p=get_bricks(obj);if(!p)return nullptr;
    try {
        auto& t=p->topology();fluxfx::BrickCoord c{x,y,z};std::string op(action);
        if(op=="activate")return PyLong_FromUnsignedLong(t.activate(c));
        if(op=="deactivate")return PyBool_FromLong(t.deactivate(c));
        if(op=="lookup")return PyLong_FromLong(t.lookup(c));
        if(op=="neighbors") {auto n=t.neighbors(c);return Py_BuildValue("(iiiiii)",n[0],n[1],n[2],n[3],n[4],n[5]);}
        throw std::invalid_argument("Unknown brick command");
    }catch(...){return cpp_error();}
}
static PyObject* brick_box(PyObject*,PyObject* args) {
    PyObject* obj;int x,y,z,nx,ny,nz;
    if(!PyArg_ParseTuple(args,"Oiiiiii",&obj,&x,&y,&z,&nx,&ny,&nz))return nullptr;
    auto* p=get_bricks(obj);if(!p)return nullptr;
    try {p->topology().activate_box({x,y,z},{nx,ny,nz});Py_RETURN_NONE;}catch(...){return cpp_error();}
}
static PyObject* brick_stats(PyObject*,PyObject* obj) {
    auto* p=get_bricks(obj);if(!p)return nullptr;
    try {
        auto s=p->stats();uint32_t capacity=0,active=0;
        if(!s.closed){capacity=p->topology().capacity();active=uint32_t(p->topology().active().size());}
        uint64_t voxels=uint64_t(p->side())*p->side()*p->side();
        return Py_BuildValue("{s:O,s:s,s:I,s:I,s:I,s:I,s:K,s:K,s:K,s:K,s:K,s:K}",
            "closed",s.closed?Py_True:Py_False,"device",s.device.c_str(),"brick_side",p->side(),
            "capacity",capacity,"active_bricks",active,"free_bricks",capacity-active,
            "active_voxels",(unsigned long long)(active*voxels),
            "field_capacity_bytes",(unsigned long long)(capacity*voxels*4),
            "gpu_topology_bytes",(unsigned long long)(capacity*28ull),
            "budget_bytes",(unsigned long long)s.budget,"resident_bytes",(unsigned long long)s.resident,
            "cpu_topology_bytes",(unsigned long long)p->cpu_bytes());
    }catch(...){return cpp_error();}
}
static PyObject* brick_probe(PyObject*,PyObject* args) {
    PyObject *obj,*r;uint64_t repeats;
    if(!PyArg_ParseTuple(args,"OO",&obj,&r) || !integer(r,repeats))return nullptr;
    auto* p=get_bricks(obj);if(!p)return nullptr;
    if(!repeats || repeats>32){PyErr_SetString(PyExc_ValueError,"Use 1..32 dispatches");return nullptr;}
    try {
        auto result=p->probe(uint32_t(repeats));auto& probe=result.probe;
        PyObject* times=PyList_New(probe.gpu_ms.size());if(!times)return nullptr;
        for(size_t i=0;i<probe.gpu_ms.size();++i) {
            PyObject* v;
            if(probe.gpu_ms[i]<0){v=Py_None;Py_INCREF(v);}else v=PyFloat_FromDouble(probe.gpu_ms[i]);
            if(!v){Py_DECREF(times);return nullptr;}PyList_SetItem(times,i,v);
        }
        auto* report=Py_BuildValue("{s:s,s:I,s:K,s:d,s:d,s:d,s:d,s:O}",
            "status",probe.mismatches?"FAIL":"PASS","mismatches",probe.mismatches,
            "active_voxels",(unsigned long long)result.active_voxels,
            "topology_ms",result.topology_ms,"prepare_ms",result.prepare_ms,
            "submit_wait_ms",probe.submit_wait_ms,"verify_ms",probe.verify_ms,"gpu_command_ms",times);
        Py_DECREF(times);return report;
    }catch(...){return cpp_error();}
}

static PyObject* brick_regions(PyObject*,PyObject* args) {
    PyObject *obj,*items;int grid,linger,halo;double dt;
    if(!PyArg_ParseTuple(args,"OOidii",&obj,&items,&grid,&dt,&linger,&halo))return nullptr;
    auto* pool=get_bricks(obj);if(!pool)return nullptr;
    auto count=PySequence_Size(items);if(count<0)return nullptr;
    if(count>64){PyErr_SetString(PyExc_ValueError,"At most 64 sources");return nullptr;}
    try {
        std::vector<fluxfx::RegionSource> sources;sources.reserve(count);
        for(Py_ssize_t i=0;i<count;++i) {
            PyObject* item=PySequence_GetItem(items,i);if(!item)return nullptr;
            fluxfx::RegionSource s{};
            bool ok=PyArg_ParseTuple(item,"ddddddd",&s.x,&s.y,&s.z,&s.radius,&s.vx,&s.vy,&s.vz);
            Py_DECREF(item);if(!ok)return nullptr;sources.push_back(s);
        }
        pool->regions().update(pool->topology(),sources,grid,dt,linger,halo);Py_RETURN_NONE;
    }catch(...){return cpp_error();}
}
static PyObject* brick_snapshot(PyObject*,PyObject* obj) {
    auto* pool=get_bricks(obj);if(!pool)return nullptr;
    try {
        auto& t=pool->topology();auto* list=PyList_New(t.active().size());if(!list)return nullptr;
        size_t i=0;
        for(auto slot:t.active()) {
            auto c=t.coord(slot);auto* row=Py_BuildValue("(iiiII)",c.x,c.y,c.z,slot,pool->regions().age(slot));
            if(!row){Py_DECREF(list);return nullptr;}PyList_SetItem(list,i++,row);
        }
        return list;
    }catch(...){return cpp_error();}
}
