void main() {
    ivec3 cell=ivec3(gl_GlobalInvocationID.xyz);
    if (any(greaterThanEqual(cell,gridSize))) return;
    ivec3 size=textureSize(inputField,0);
    float m=0.0;
    for (int z=0;z<4;++z) for (int y=0;y<4;++y) for (int x=0;x<4;++x) {
        ivec3 p=cell*4+ivec3(x,y,z);
        if (any(greaterThanEqual(p,size))) continue;
        float v=texelFetch(inputField,p,0).r;
        m=max(m, (isnan(v)||isinf(v)) ? 3.4e38 : abs(v));
    }
    imageStore(outputField,cell,vec4(m,0.0,0.0,1.0));
}
