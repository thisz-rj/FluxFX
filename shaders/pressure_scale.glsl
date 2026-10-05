void main()
{
    ivec3 c=ivec3(gl_GlobalInvocationID.xyz);
    if(any(greaterThanEqual(c,gridSize)))return;
    imageStore(outputField,c,vec4(texelFetch(inputField,c,0).r*factor,0,0,1));
}
