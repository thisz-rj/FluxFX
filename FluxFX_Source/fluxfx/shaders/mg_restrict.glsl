// Equal-volume restriction; only used for exact factor-two coarsening.
void main() {
    ivec3 c=ivec3(gl_GlobalInvocationID.xyz);
    if(any(greaterThanEqual(c,gridSize))) return;
    float value=0.0;
    for(int z=0;z<2;++z) for(int y=0;y<2;++y) for(int x=0;x<2;++x)
        value+=texelFetch(inputField,2*c+ivec3(x,y,z),0).r;
    imageStore(outputField,c,vec4(value/8.0,0.0,0.0,1.0));
}
