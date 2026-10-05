float transportedScalar(ivec3 cell,vec3 departure,vec3 h)
{
    vec3 q=departure/h-vec3(0.5);
    float lowOrder=sampleClosed(q);
    if (correctedTransport<0.5) return lowOrder;
    // Reverse tracing also crosses boundaries: prefer first order there.
    vec3 p=(vec3(cell)+vec3(0.5))*h;
    vec3 reverseMidpoint=p+0.5*dt*velocityAt(p);
    vec3 arrival=p+dt*velocityAt(reverseMidpoint);
#ifdef FLUXFX_COLLISIONS
    if(!safeSolidCorrection(p,departure,reverseMidpoint,arrival,domainExtent))return lowOrder;
#endif
    if (any(lessThan(departure,0.5*h)) || any(greaterThan(departure,domainExtent-0.5*h)) ||
        any(lessThan(arrival,0.5*h)) || any(greaterThan(arrival,domainExtent-0.5*h))) return lowOrder;
    float value=texelFetch(predictorField,cell,0).r+0.5*(fetchClosed(cell)-texelFetch(reverseField,cell,0).r);
    ivec3 b=ivec3(floor(q));float lo=fetchClosed(b);float hi=lo;
    for(int z=0;z<2;z++)for(int y=0;y<2;y++)for(int x=0;x<2;x++) {
        float v=fetchClosed(b+ivec3(x,y,z));lo=min(lo,v);hi=max(hi,v);
    }
    return clamp(value,lo,hi);
}
