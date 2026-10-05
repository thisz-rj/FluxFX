vec4 curlAt(ivec3 c)
{
    return texelFetch(curlField,clamp(c,ivec3(0),textureSize(curlField,0)-ivec3(1)),0);
}
vec3 forceAt(ivec3 c)
{
    vec3 gradient=0.5*invCell*vec3(curlAt(c+ivec3(1,0,0)).a-curlAt(c-ivec3(1,0,0)).a,
        curlAt(c+ivec3(0,1,0)).a-curlAt(c-ivec3(0,1,0)).a,
        curlAt(c+ivec3(0,0,1)).a-curlAt(c-ivec3(0,0,1)).a);
    float magnitude=length(gradient);
    if(magnitude<1e-8)return vec3(0);
    float h=1.0/max(invCell.x,max(invCell.y,invCell.z));
    vec3 force=curlStrength*h*cross(gradient/magnitude,curlAt(c).xyz);
    return force*min(1.0,forceLimit/max(length(force),1e-12));
}
void main()
{
    ivec3 c=ivec3(gl_GlobalInvocationID.xyz);
    if(any(greaterThanEqual(c,gridSize)))return;
    vec3 force=0.5*(forceAt(c)+forceAt(c-ivec3(axisMask)));
    float value=texelFetch(inputField,c,0).r+dt*dot(force,axisMask);
    imageStore(outputField,c,vec4(value,0,0,1));
}
