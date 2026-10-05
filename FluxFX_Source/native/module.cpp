#define Py_LIMITED_API 0x03090000
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include "core.hpp"
#include "resources.hpp"
#include "transport.hpp"
#include "mac.hpp"
#include "projection.hpp"
#include "brick_pool.hpp"
#include <stdexcept>
#include <exception>

static PyObject* run_probe(PyObject*, PyObject* args, PyObject* kwargs) {
    unsigned long long count=1048576,repeats=4,seed=17;
    static const char* names[]={"count","repeats","seed",nullptr};
    PyObject *count_obj=nullptr, *repeats_obj=nullptr, *seed_obj=nullptr;
    if (!PyArg_ParseTupleAndKeywords(args,kwargs,"|OOO",const_cast<char**>(names),&count_obj,&repeats_obj,&seed_obj)) return nullptr;
    if (count_obj) count=PyLong_AsUnsignedLongLong(count_obj);
    if (PyErr_Occurred()) return nullptr;
    if (repeats_obj) repeats=PyLong_AsUnsignedLongLong(repeats_obj);
    if (PyErr_Occurred()) return nullptr;
    if (seed_obj) seed=PyLong_AsUnsignedLongLong(seed_obj);
    if (PyErr_Occurred()) return nullptr;
    if (count<1 || count>16777216 || repeats<1 || repeats>32 || seed>UINT32_MAX) {
        PyErr_SetString(PyExc_ValueError,"count: 1..16777216; repeats: 1..32; seed: 0..4294967295"); return nullptr;
    }
    try {
        auto r=fluxfx::probe(static_cast<uint32_t>(count),static_cast<uint32_t>(repeats),static_cast<uint32_t>(seed));
        PyObject* times=PyList_New(r.gpu_ms.size());
        if (!times) return nullptr;
        for (size_t i=0;i<r.gpu_ms.size();++i) {
            PyObject* value;
            if (r.gpu_ms[i]<0) { value=Py_None; Py_INCREF(value); }
            else value=PyFloat_FromDouble(r.gpu_ms[i]);
            if (!value) { Py_DECREF(times); return nullptr; }
            PyList_SetItem(times,i,value);
        }
        PyObject* report=Py_BuildValue("{s:s,s:s,s:s,s:O,s:K,s:K,s:I,s:I,s:I,s:I,s:d,s:d,s:d,s:O,s:s}",
            "status",r.mismatches ? "FAIL" : "PASS", "backend","METAL", "device",r.device.c_str(),
            "unified_memory",r.unified ? Py_True : Py_False,
            "max_buffer_bytes",static_cast<unsigned long long>(r.max_buffer_bytes),
            "buffer_bytes",static_cast<unsigned long long>(r.buffer_bytes),
            "count",r.count,"repeats",r.repeats,"seed",r.seed,"mismatches",r.mismatches,
            "setup_ms",r.setup_ms,"submit_wait_ms",r.submit_wait_ms,"verify_ms",r.verify_ms,
            "gpu_command_ms",times,"resource_lifetime","probe-scoped; released before return");
        Py_DECREF(times);return report;
    } catch (const std::exception& error) {
        PyErr_SetString(PyExc_RuntimeError,error.what());return nullptr;
    }
}
static constexpr const char* context_name="fluxfx_core.Context";
static fluxfx::Context* get_context(PyObject* obj) {
    return static_cast<fluxfx::Context*>(PyCapsule_GetPointer(obj,context_name));
}
static void destroy_context(PyObject* capsule) {
    auto* context=get_context(capsule);
    if(context) delete context;
    else PyErr_Clear();
}
static PyObject* cpp_error() {
    try { throw; }
    catch(const std::invalid_argument& e) { PyErr_SetString(PyExc_ValueError,e.what()); }
    catch(const std::bad_alloc&) { PyErr_NoMemory(); }
    catch(const std::exception& e) { PyErr_SetString(PyExc_RuntimeError,e.what()); }
    catch(...) { PyErr_SetString(PyExc_RuntimeError,"Unknown native failure"); }
    return nullptr;
}
static bool integer(PyObject* value,uint64_t& out) {
    out=PyLong_AsUnsignedLongLong(value);return !PyErr_Occurred();
}
static PyObject* create_context(PyObject*,PyObject* value) {
    uint64_t budget;if(!integer(value,budget)) return nullptr;
    try {
        auto context=std::make_unique<fluxfx::Context>(budget);
        PyObject* capsule=PyCapsule_New(context.get(),context_name,destroy_context);
        if(capsule) context.release();
        return capsule;
    } catch(...) { return cpp_error(); }
}
static PyObject* context_close(PyObject*,PyObject* obj) {
    auto* context=get_context(obj);if(!context) return nullptr;
    try { context->close();Py_RETURN_NONE; } catch(...) {return cpp_error();}
}
static PyObject* context_allocate(PyObject*,PyObject* args) {
    PyObject *obj,*size;if(!PyArg_ParseTuple(args,"OO",&obj,&size)) return nullptr;
    auto* context=get_context(obj);uint64_t bytes;if(!context || !integer(size,bytes)) return nullptr;
    try {return PyLong_FromUnsignedLongLong(context->allocate(bytes));} catch(...) {return cpp_error();}
}
static PyObject* context_release(PyObject*,PyObject* args) {
    PyObject *obj,*handle;if(!PyArg_ParseTuple(args,"OO",&obj,&handle)) return nullptr;
    auto* context=get_context(obj);uint64_t id;if(!context || !integer(handle,id)) return nullptr;
    try {context->release(id);Py_RETURN_NONE;} catch(...) {return cpp_error();}
}
static PyObject* context_stats(PyObject*,PyObject* obj) {
    auto* context=get_context(obj);if(!context) return nullptr;
    try {
        auto s=context->stats();
        return Py_BuildValue("{s:s,s:O,s:O,s:K,s:K,s:K,s:K,s:K,s:K,s:K,s:K,s:K,s:K,s:K,s:i}",
          "device",s.device.c_str(),"closed",s.closed?Py_True:Py_False,"unified_memory",s.unified?Py_True:Py_False,
          "budget_bytes",(unsigned long long)s.budget,"resident_bytes",(unsigned long long)s.resident,
          "used_bytes",(unsigned long long)s.used,"peak_used_bytes",(unsigned long long)s.peak,
          "active_allocations",(unsigned long long)s.active,"allocation_requests",(unsigned long long)s.allocations,
          "largest_free_bytes",(unsigned long long)s.largest_free,"max_buffer_bytes",(unsigned long long)s.max_buffer,
          "recommended_working_set_bytes",(unsigned long long)s.recommended_working_set,
          "thread_execution_width",(unsigned long long)s.thread_width,"max_threads_per_group",(unsigned long long)s.max_threads,
          "backing_buffer_allocations",s.closed?0:1);
    } catch(...) {return cpp_error();}
}
static PyObject* context_dispatch(PyObject*,PyObject* args) {
    PyObject *obj,*handle,*count_obj,*repeats_obj,*seed_obj;
    if(!PyArg_ParseTuple(args,"OOOOO",&obj,&handle,&count_obj,&repeats_obj,&seed_obj)) return nullptr;
    auto* context=get_context(obj);uint64_t id,count,repeats,seed;
    if(!context || !integer(handle,id) || !integer(count_obj,count) || !integer(repeats_obj,repeats) || !integer(seed_obj,seed)) return nullptr;
    if(count>UINT32_MAX || repeats>32 || seed>UINT32_MAX) {PyErr_SetString(PyExc_ValueError,"Probe arguments out of range");return nullptr;}
    try {
        auto r=context->dispatch(id,(uint32_t)count,(uint32_t)repeats,(uint32_t)seed);
        PyObject* times=PyList_New(r.gpu_ms.size());if(!times) return nullptr;
        for(size_t i=0;i<r.gpu_ms.size();++i) {
            PyObject* value;
            if(r.gpu_ms[i]<0) {value=Py_None;Py_INCREF(value);} else value=PyFloat_FromDouble(r.gpu_ms[i]);
            if(!value) {Py_DECREF(times);return nullptr;} PyList_SetItem(times,i,value);
        }
        auto* report=Py_BuildValue("{s:s,s:I,s:d,s:d,s:O}","status",r.mismatches?"FAIL":"PASS",
          "mismatches",r.mismatches,"submit_wait_ms",r.submit_wait_ms,"verify_ms",r.verify_ms,"gpu_command_ms",times);
        Py_DECREF(times);return report;
    } catch(...) {return cpp_error();}
}
static PyObject* context_verify(PyObject*,PyObject* args) {
    PyObject *obj,*handle,*count_obj,*seed_obj;
    if(!PyArg_ParseTuple(args,"OOOO",&obj,&handle,&count_obj,&seed_obj)) return nullptr;
    auto* context=get_context(obj);uint64_t id,count,seed;
    if(!context || !integer(handle,id) || !integer(count_obj,count) || !integer(seed_obj,seed)) return nullptr;
    if(count>UINT32_MAX || seed>UINT32_MAX) {PyErr_SetString(PyExc_ValueError,"Probe arguments out of range");return nullptr;}
    try {return PyLong_FromUnsignedLong(context->verify(id,(uint32_t)count,(uint32_t)seed));} catch(...) {return cpp_error();}
}
static PyObject* resource_status(PyObject*, PyObject*) {
    return Py_BuildValue("{s:K}","owned_buffer_bytes",static_cast<unsigned long long>(fluxfx::owned_buffer_bytes()+fluxfx::arena_owned_buffer_bytes()+fluxfx::transport_owned_bytes()+fluxfx::mac_owned_bytes()+fluxfx::projection_owned_bytes()));
}
static PyObject* transport_compare(PyObject*,PyObject* args) {
    int n,side,steps;double dx,dy,dz;PyObject* budget_obj;uint64_t budget;
    if(!PyArg_ParseTuple(args,"iiidddO",&n,&side,&steps,&dx,&dy,&dz,&budget_obj) || !integer(budget_obj,budget))return nullptr;
    try {
        auto r=fluxfx::compare_transport(n,side,steps,float(dx),float(dy),float(dz),budget);
        PyObject* a=PyList_New(r.sparse_gpu_ms.size());if(!a)return nullptr;
        PyObject* b=PyList_New(r.dense_gpu_ms.size());if(!b){Py_DECREF(a);return nullptr;}
        for(size_t i=0;i<r.sparse_gpu_ms.size();++i) {
            auto* x=PyFloat_FromDouble(r.sparse_gpu_ms[i]);auto* y=PyFloat_FromDouble(r.dense_gpu_ms[i]);
            if(!x || !y){Py_XDECREF(x);Py_XDECREF(y);Py_DECREF(a);Py_DECREF(b);return nullptr;}
            PyList_SetItem(a,i,x);PyList_SetItem(b,i,y);
        }
        auto* data=PyBytes_FromStringAndSize(reinterpret_cast<const char*>(r.density.data()),r.density.size()*sizeof(float));
        if(!data){Py_DECREF(a);Py_DECREF(b);return nullptr;}
        auto* result=Py_BuildValue("{s:I,s:I,s:I,s:I,s:K,s:K,s:d,s:d,s:d,s:d,s:d,s:d,s:d,s:d,s:d,s:d,s:O,s:O,s:O}",
            "resolution",r.resolution,"side",r.side,"steps",r.steps,"active_bricks",r.active_bricks,
            "sparse_bytes",(unsigned long long)r.sparse_bytes,"dense_bytes",(unsigned long long)r.dense_bytes,
            "topology_ms",r.topology_ms,"sparse_setup_ms",r.sparse_setup_ms,"dense_setup_ms",r.dense_setup_ms,
            "sparse_wall_ms",r.sparse_wall_ms,"dense_wall_ms",r.dense_wall_ms,"max_error",r.max_error,
            "rms_error",r.rms_error,"sparse_mass",r.sparse_mass,"dense_mass",r.dense_mass,"initial_mass",r.initial_mass,
            "sparse_gpu_ms",a,"dense_gpu_ms",b,"density",data);
        Py_DECREF(a);Py_DECREF(b);Py_DECREF(data);return result;
    }catch(...){return cpp_error();}
}
static PyObject* mac_compare(PyObject*,PyObject* args) {
    int n,side,steps,mode;PyObject* budget_obj;uint64_t budget;
    if(!PyArg_ParseTuple(args,"iiiiO",&n,&side,&steps,&mode,&budget_obj) || !integer(budget_obj,budget))return nullptr;
    try {
        auto r=fluxfx::compare_mac(n,side,steps,mode,budget);
        auto* a=PyList_New(r.sparse_gpu_ms.size());if(!a)return nullptr;
        auto* b=PyList_New(r.dense_gpu_ms.size());if(!b){Py_DECREF(a);return nullptr;}
        for(size_t i=0;i<r.sparse_gpu_ms.size();++i){
            auto* x=PyFloat_FromDouble(r.sparse_gpu_ms[i]);auto* y=PyFloat_FromDouble(r.dense_gpu_ms[i]);
            if(!x || !y){Py_XDECREF(x);Py_XDECREF(y);Py_DECREF(a);Py_DECREF(b);return nullptr;}
            PyList_SetItem(a,i,x);PyList_SetItem(b,i,y);
        }
        auto* data=PyBytes_FromStringAndSize(reinterpret_cast<const char*>(r.faces.data()),r.faces.size()*sizeof(float));
        if(!data){Py_DECREF(a);Py_DECREF(b);return nullptr;}
        auto* result=Py_BuildValue("{s:I,s:I,s:I,s:I,s:K,s:K,s:K,s:K,s:d,s:d,s:d,s:d,s:d,s:d,s:O,s:O,s:O}",
            "resolution",r.resolution,"side",r.side,"steps",r.steps,"active_bricks",r.active_bricks,
            "sparse_bytes",(unsigned long long)r.sparse_bytes,"dense_bytes",(unsigned long long)r.dense_bytes,
            "owned_faces",(unsigned long long)r.owned_faces,"padding_faces",(unsigned long long)r.padding_faces,
            "max_error",r.max_error,"rms_error",r.rms_error,"padding_error",r.padding_error,"topology_ms",r.topology_ms,
            "sparse_wall_ms",r.sparse_wall_ms,"dense_wall_ms",r.dense_wall_ms,"sparse_gpu_ms",a,"dense_gpu_ms",b,"faces",data);
        Py_DECREF(a);Py_DECREF(b);Py_DECREF(data);return result;
    }catch(...){return cpp_error();}
}
static PyObject* projection_compare(PyObject*,PyObject* args) {
 int n,side,iterations,mode,cycles=0,steps=0,schedule=0,dense_full=0,global_support=0,hybrid=0,adaptive=0,pooled=0;PyObject* obj;uint64_t budget;
 if(!PyArg_ParseTuple(args,"iiiiO|iiiiiiii",&n,&side,&iterations,&mode,&obj,&cycles,&steps,&schedule,&dense_full,&global_support,&hybrid,&adaptive,&pooled)||!integer(obj,budget))return nullptr;
 try {
  auto r=fluxfx::compare_projection(n,side,iterations,mode,budget,cycles,steps,schedule,dense_full!=0,global_support!=0,hybrid!=0,adaptive!=0,pooled!=0);
  auto* d=PyDict_New();if(!d)return nullptr;
  auto put=[&](const char* key,PyObject* v){if(!v)return false;int ok=PyDict_SetItemString(d,key,v);Py_DECREF(v);return ok==0;};
  bool ok=true;
#define NUMBER(k) ok=ok && put(#k,PyFloat_FromDouble(double(r.k)));
#define INTEGER(k) ok=ok && put(#k,PyLong_FromUnsignedLongLong(r.k));
  INTEGER(resolution) INTEGER(side) INTEGER(iterations) INTEGER(mode) INTEGER(active_bricks) INTEGER(solve_cells) INTEGER(cycles) INTEGER(levels) INTEGER(steps) INTEGER(schedule) INTEGER(dense_full) INTEGER(global_support) INTEGER(hybrid) INTEGER(adaptive) INTEGER(pooled) INTEGER(global_copy_bytes) INTEGER(density_capacity) INTEGER(density_reallocations) INTEGER(density_reuses) INTEGER(expansions) INTEGER(preserved_bytes) INTEGER(peak_sparse_bytes) INTEGER(density_cells) INTEGER(density_bytes) INTEGER(density_bricks)
  INTEGER(sparse_bytes) INTEGER(dense_bytes) INTEGER(sparse_hierarchy_bytes) INTEGER(dense_hierarchy_bytes)
#undef INTEGER
  NUMBER(preflight_ms) NUMBER(density_topology_ms) NUMBER(divergence_error) NUMBER(dense_after_rms) NUMBER(density_error) NUMBER(sparse_mass) NUMBER(dense_mass) NUMBER(injected_mass) NUMBER(topology_ms) NUMBER(max_error) NUMBER(pressure_error) NUMBER(before_rms) NUMBER(after_rms)
  NUMBER(residual_rms) NUMBER(wall_error) NUMBER(padding_error) NUMBER(sparse_wall_ms) NUMBER(dense_wall_ms) NUMBER(sparse_gpu_ms) NUMBER(dense_gpu_ms)
#undef NUMBER
#define DATA(k) ok=ok && put(#k,PyBytes_FromStringAndSize(reinterpret_cast<const char*>(r.k.data()),r.k.size()*sizeof(float)));
  if(steps){DATA(density)} DATA(faces) DATA(pressure) DATA(before) DATA(after)
#undef DATA
  if(!ok){Py_DECREF(d);return nullptr;}return d;
 }catch(...){return cpp_error();}
}
#include "brick_bindings.inc"
static PyMethodDef methods[]={
    {"projection_compare",projection_compare,METH_VARARGS,"Compare fixed-region sparse and dense Jacobi projection."},
    {"mac_compare",mac_compare,METH_VARARGS,"Compare sparse and dense staggered MAC velocity transport."},
    {"transport_compare",transport_compare,METH_VARARGS,"Compare prescribed-velocity sparse and dense scalar transport."},
    {"brick_regions",brick_regions,METH_VARARGS,"Update source swept regions with delayed deactivation."},
    {"brick_snapshot",brick_snapshot,METH_O,"Snapshot compact active coordinates, slots and ages."},
    {"brick_create",brick_create,METH_VARARGS,"Preallocate a sparse brick pool."},
    {"brick_close",brick_close,METH_O,"Close a brick pool."},
    {"brick_command",brick_command,METH_VARARGS,"Activate, deactivate or query a coordinate."},
    {"brick_box",brick_box,METH_VARARGS,"Activate a bounded brick box with atomic capacity preflight."},
    {"brick_stats",brick_stats,METH_O,"Brick counts and memory accounting."},
    {"brick_probe",brick_probe,METH_VARARGS,"Verify active-only GPU dispatch and neighbor IDs."},
    {"create_context",create_context,METH_O,"Preallocate a bounded shared Metal arena."},
    {"close_context",context_close,METH_O,"Release context resources; idempotent."},
    {"context_stats",context_stats,METH_O,"Owned memory and device capabilities."},
    {"allocate",context_allocate,METH_VARARGS,"Suballocate a reusable aligned buffer range."},
    {"release",context_release,METH_VARARGS,"Return an allocation to its arena."},
    {"dispatch",context_dispatch,METH_VARARGS,"Fill and verify a range using the cached pipeline."},
    {"verify",context_verify,METH_VARARGS,"Check an existing allocation without GPU writes."},
    {"resource_status",resource_status,METH_NOARGS,"Native probe-owned buffer bytes; excludes driver and Blender allocations."},
    {"run_probe",reinterpret_cast<PyCFunction>(reinterpret_cast<void(*)(void)>(run_probe)),METH_VARARGS|METH_KEYWORDS,
     "Allocate a shared Metal buffer, run a bounded integer kernel, verify and release."},
    {nullptr,nullptr,0,nullptr}
};
static PyModuleDef module={PyModuleDef_HEAD_INIT,"fluxfx_core","FluxFX P1.2 native sparse brick pool.",0,methods,nullptr,nullptr,nullptr,nullptr};
PyMODINIT_FUNC PyInit_fluxfx_core() { return PyModule_Create(&module); }
