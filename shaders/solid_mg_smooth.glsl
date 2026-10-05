void main() {
    ivec3 c=ivec3(gl_GlobalInvocationID.xyz);
    if(any(greaterThanEqual(c,gridSize)))return;
    float diagonal,neighbors;graphTerms(c,diagonal,neighbors);
    float value=diagonal>0.0 ? mix(texelFetch(inputField,c,0).r,
        (neighbors-texelFetch(divergenceField,c,0).r)/diagonal,2.0/3.0) : 0.0;
    imageStore(outputField,c,vec4(value,0,0,1));
}
