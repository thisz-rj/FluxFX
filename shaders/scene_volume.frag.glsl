void main() {
    vec4 a=clipToDomain*vec4(screenPosition,-1.0,1.0);
    vec4 b=clipToDomain*vec4(screenPosition,1.0,1.0);
    vec3 origin=a.xyz/a.w;
    vec3 direction=b.xyz/b.w-origin;
    float nearT=0.0,farT=1.0;
    bool hit=true;
    for(int axis=0;axis<3;++axis) {
        float d=direction[axis],o=origin[axis];
        if(abs(d)<1e-8) {
            if(o<0.0 || o>1.0) hit=false;
        } else {
            float u=-o/d,v=(1.0-o)/d;
            nearT=max(nearT,min(u,v));farT=min(farT,max(u,v));
        }
    }
    vec3 color=vec3(0.0);
    float transmittance=1.0;
    if(hit && farT>nearT) {
        float ds=(farT-nearT)*length(direction)/float(raySteps);
        for(int i=0;i<256;++i) {
            if(i>=raySteps || transmittance<0.001) break;
            float t=mix(nearT,farT,(float(i)+0.5)/float(raySteps));
            float value=fieldAt(origin+t*direction);
            float density=(thermalView>0.5 && thermalView<1.5) ? abs(value)/100.0 : max(value,0.0);
            float alpha=1.0-exp(-exposure*density*ds);
            vec3 tint=thermalView>1.5 ? mix(vec3(1.0,0.12,0.01),vec3(1.0,0.9,0.45),clamp(value/4.0,0.0,1.0)) : thermalView>0.5 ? (value>=0.0 ? vec3(1.0,0.35,0.08) : vec3(0.1,0.4,1.0)) : vec3(0.67,0.84,0.94);
            color+=transmittance*alpha*tint;
            transmittance*=1.0-alpha;
        }
    }
    // Premultiplied colour: preserve the Blender viewport behind the smoke.
    fragColor=vec4(color,1.0-transmittance);
}
