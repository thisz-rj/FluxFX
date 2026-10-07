// Cell-centred trilinear correction with Neumann extension.
void main() {
    ivec3 c=ivec3(gl_GlobalInvocationID.xyz);
    if(any(greaterThanEqual(c,gridSize))) return;
    vec3 q=(vec3(c)+0.5)*0.5-0.5;
    ivec3 b=ivec3(floor(q));vec3 f=fract(q);
    ivec3 size=textureSize(coarseField,0);
    float value=0.0;
    for(int z=0;z<2;++z) for(int y=0;y<2;++y) for(int x=0;x<2;++x) {
        ivec3 offset=ivec3(x,y,z);
        vec3 w=mix(vec3(1.0)-f,f,vec3(offset));
        value+=w.x*w.y*w.z*texelFetch(coarseField,clamp(b+offset,ivec3(0),size-1),0).r;
    }
    imageStore(outputField,c,vec4(texelFetch(inputField,c,0).r+value,0.0,0.0,1.0));
}
