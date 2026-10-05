void main() {
    ivec3 c=ivec3(gl_GlobalInvocationID.xyz);
    if(any(greaterThanEqual(c,gridSize)))return;
    float diagonal,neighbors;graphTerms(c,diagonal,neighbors);
    float value=diagonal>0.0 ? texelFetch(divergenceField,c,0).r-neighbors+
        diagonal*texelFetch(inputField,c,0).r : 0.0;
    imageStore(outputField,c,vec4(value,0,0,1));
}
