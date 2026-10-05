void main()
{
    ivec3 cell = ivec3(gl_GlobalInvocationID.xyz);
    if (any(greaterThanEqual(cell, gridSize))) { return; }
#ifdef FLUXFX_COLLISIONS
    if(solidFace(cell,int(dot(axisMask,vec3(0,1,2))))) { imageStore(outputField,cell,vec4(0)); return; }
#endif
    vec3 p = (vec3(cell) + faceOffset) * domainExtent / cellCount;
    vec3 midpoint = p - 0.5 * dt * velocityAt(p);
#ifdef FLUXFX_COLLISIONS
    midpoint = clipSolidTrace(p,midpoint,domainExtent);
#endif
    vec3 departure = p - dt * velocityAt(midpoint);
#ifdef FLUXFX_COLLISIONS
    departure = clipSolidTrace(p,departure,domainExtent);
#endif
    float value = transportedVelocity(cell,p,departure);
    float totalCoupling=0.0;
    float weightedTarget=0.0;
    for (int i=0;i<8;i++) {
        if (float(i)>=sourceCount) break;
        float rate=sourceValue(i,3,1)*tableWeight(i,p);
        totalCoupling+=rate;
        weightedTarget+=rate*dot(sourceVector(i,2),axisMask);
    }
    // Sum relaxation rates first: overlapping jets are independent of list order.
    if (totalCoupling>0.0) {
        value=mix(value,weightedTarget/totalCoupling,1.0-exp(-dt*totalCoupling));
    }
    imageStore(outputField, cell, vec4(value, 0.0, 0.0, 1.0));
}
