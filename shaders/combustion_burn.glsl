void main() {
    ivec3 cell=ivec3(gl_GlobalInvocationID.xyz);
    if(any(greaterThanEqual(cell,gridSize)))return;
    float fuel=max(texelFetch(inputField,cell,0).r,0.0);
    float temperature=texelFetch(temperatureField,cell,0).r;
    float burned=temperature>=ignitionTemperature ? fuel*(1.0-exp(-burnRate*dt)) : 0.0;
    imageStore(outputField,cell,vec4(burned/dt,0,0,1));
}
