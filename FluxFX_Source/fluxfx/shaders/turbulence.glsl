vec4 waveRow(int row,int wave) {
    return vec4(texelFetch(waveTable,ivec3(0,row,wave),0).r,texelFetch(waveTable,ivec3(1,row,wave),0).r,
                texelFetch(waveTable,ivec3(2,row,wave),0).r,texelFetch(waveTable,ivec3(3,row,wave),0).r);
}
void main() {
    ivec3 face=ivec3(gl_GlobalInvocationID.xyz);
    if(any(greaterThanEqual(face,gridSize)))return;
    ivec3 cells=textureSize(densityField,0);
    vec3 p=(vec3(face)+faceOffset)*domainExtent/vec3(cells);
    vec3 force=vec3(0);
    for(int i=0;i<12;i++) {
        vec4 k=waveRow(0,i),a=waveRow(1,i);
        force+=a.xyz*sin(dot(k.xyz,p)+k.w+phaseTime*a.w);
    }
    force*=strength;
    force*=min(1.0,forceLimit/max(length(force),1e-12));
    if(maskMode>0.5) {
        ivec3 lo=clamp(face-ivec3(axisMask),ivec3(0),cells-1),hi=clamp(face,ivec3(0),cells-1);
        float value=maskMode<1.5 ? .5*(texelFetch(densityField,lo,0).r+texelFetch(densityField,hi,0).r)
                                  : .5*(texelFetch(temperatureField,lo,0).r+texelFetch(temperatureField,hi,0).r);
        force*=clamp(value/maskThreshold,0.0,1.0);
    }
    imageStore(outputField,face,vec4(texelFetch(inputField,face,0).r+dt*dot(force,axisMask),0,0,1));
}
