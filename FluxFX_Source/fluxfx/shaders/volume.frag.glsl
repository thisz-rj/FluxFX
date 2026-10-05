// Orthographic preview of the complete unit box; no scene depth compositing.
void main() {
    vec3 origin = vec3(0.5) - 2.0 * viewForward
        + 1.8 * ((sliceUV.x-0.5)*viewRight + (sliceUV.y-0.5)*viewUp);
    float nearT = 0.0, farT = 4.0;
    bool hit = true;
    for (int axis=0; axis<3; ++axis) {
        float d = viewForward[axis], o = origin[axis];
        if (abs(d)<1e-7) {
            if (o<0.0 || o>1.0) hit=false;
        } else {
            float a = -o/d, b = (1.0-o)/d;
            nearT=max(nearT,min(a,b)); farT=min(farT,max(a,b));
        }
    }
    vec3 bg = vec3(0.018,0.029,0.044);
    vec3 color = vec3(0.0);
    float transmittance=1.0;
    if (hit && farT>nearT) {
        float ds=(farT-nearT)/float(raySteps);
        for (int i=0; i<256; ++i) {
            if (i>=raySteps || transmittance<0.001) break;
            vec3 p=origin+viewForward*(nearT+(float(i)+0.5)*ds);
            float value=fieldAt(p);
            float d=(thermalView>0.5 && thermalView<1.5) ? abs(value)/100.0 : max(value,0.0);
            float alpha=1.0-exp(-exposure*d*ds);
            vec3 tint=thermalView>1.5 ? mix(vec3(1.0,0.12,0.01),vec3(1.0,0.9,0.45),clamp(value/4.0,0.0,1.0)) : thermalView>0.5 ? (value>=0.0 ? vec3(1.0,0.35,0.08) : vec3(0.1,0.4,1.0)) : vec3(0.67,0.84,0.94);
            color+=transmittance*alpha*tint;
            transmittance*=1.0-alpha;
        }
    }
    fragColor=vec4(color+transmittance*bg,1.0);
}
