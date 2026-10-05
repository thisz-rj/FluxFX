vec3 centeredVelocity(ivec3 c)
{
    c=clamp(c,ivec3(0),gridSize-ivec3(1));
    return 0.5*vec3(texelFetch(velocityU,c,0).r+texelFetch(velocityU,c+ivec3(1,0,0),0).r,
                    texelFetch(velocityV,c,0).r+texelFetch(velocityV,c+ivec3(0,1,0),0).r,
                    texelFetch(velocityW,c,0).r+texelFetch(velocityW,c+ivec3(0,0,1),0).r);
}
void main()
{
    ivec3 c=ivec3(gl_GlobalInvocationID.xyz);
    if(any(greaterThanEqual(c,gridSize)))return;
    vec3 dx=(centeredVelocity(c+ivec3(1,0,0))-centeredVelocity(c-ivec3(1,0,0)))*0.5*invCell.x;
    vec3 dy=(centeredVelocity(c+ivec3(0,1,0))-centeredVelocity(c-ivec3(0,1,0)))*0.5*invCell.y;
    vec3 dz=(centeredVelocity(c+ivec3(0,0,1))-centeredVelocity(c-ivec3(0,0,1)))*0.5*invCell.z;
    vec3 omega=vec3(dy.z-dz.y,dz.x-dx.z,dx.y-dy.x);
    imageStore(outputField,c,vec4(omega,length(omega)));
}
