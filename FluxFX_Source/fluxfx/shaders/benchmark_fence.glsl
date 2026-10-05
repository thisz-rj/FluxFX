// Completion dependency on each final field. Readback includes fence overhead.
void main() {
    ivec3 cell=ivec3(gl_GlobalInvocationID.xyz);
    if (any(greaterThanEqual(cell,gridSize))) return;
    float value=texelFetch(densityField,ivec3(0),0).r
        +texelFetch(temperatureField,ivec3(0),0).r
        +texelFetch(velocityU,ivec3(0),0).r
        +texelFetch(velocityV,ivec3(0),0).r
        +texelFetch(velocityW,ivec3(0),0).r
        +texelFetch(divergenceField,ivec3(0),0).r
        +texelFetch(fuelField,ivec3(0),0).r+texelFetch(flameField,ivec3(0),0).r;
    imageStore(outputField,cell,vec4(value,0.0,0.0,1.0));
}
