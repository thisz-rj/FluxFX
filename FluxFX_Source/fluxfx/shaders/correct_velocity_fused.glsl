float faceOriginal(ivec3 c)
{
    return texelFetch(originalFaceField,clamp(c,ivec3(0),gridSize-ivec3(1)),0).r;
}
float transportedVelocity(ivec3 cell,vec3 p,vec3 departure)
{
    vec3 h=domainExtent/cellCount;
    float lowOrder=sampleFace(originalFaceField,departure/h-faceOffset);
    if(correctedVelocity<0.5)return lowOrder;
    vec3 loBound=faceOffset*h;
    vec3 hiBound=(vec3(gridSize-ivec3(1))+faceOffset)*h;
    vec3 midpoint=p+0.5*dt*velocityAt(p);
    vec3 arrival=p+dt*velocityAt(midpoint);
#ifdef FLUXFX_COLLISIONS
    if(!safeSolidCorrection(p,departure,midpoint,arrival,domainExtent))return lowOrder;
#endif
    if(any(lessThan(departure,loBound)) || any(greaterThan(departure,hiBound)) ||
       any(lessThan(arrival,loBound)) || any(greaterThan(arrival,hiBound)))return lowOrder;
    float value=texelFetch(facePredictor,cell,0).r+0.5*(faceOriginal(cell)-sampleFace(facePredictor,arrival/h-faceOffset));
    ivec3 b=ivec3(floor(departure/h-faceOffset));
    float lo=faceOriginal(b),hi=lo;
    for(int z=0;z<2;z++)for(int y=0;y<2;y++)for(int x=0;x<2;x++){
        float v=faceOriginal(b+ivec3(x,y,z));lo=min(lo,v);hi=max(hi,v);
    }
    // Blend with first-order transport to retain damping in the coupled solver.
    return mix(lowOrder,clamp(value,lo,hi),0.5);
}
