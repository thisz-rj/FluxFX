void main()
{
    ivec3 cell=ivec3(gl_GlobalInvocationID.xyz);
    if (any(greaterThanEqual(cell,gridSize))) return;
#ifdef FLUXFX_COLLISIONS
    if(solidCell(cell)) { imageStore(outputField,cell,vec4(0)); return; }
#endif
    vec3 h=domainExtent/vec3(gridSize);
    vec3 p=(vec3(cell)+vec3(0.5))*h;
    vec3 midpoint=p-0.5*dt*velocityAt(p);
#ifdef FLUXFX_COLLISIONS
    midpoint=clipSolidTrace(p,midpoint,domainExtent);
#endif
    vec3 departure=p-dt*velocityAt(midpoint);
#ifdef FLUXFX_COLLISIONS
    departure=clipSolidTrace(p,departure,domainExtent);
#endif
    imageStore(outputField,cell,vec4(sampleClosed(departure/h-vec3(0.5)),0,0,1));
}
