// One-sided scalar extension at top/bottom faces; no solid wall condition.
void main()
{
    ivec3 face = ivec3(gl_GlobalInvocationID.xyz);
    if (any(greaterThanEqual(face, gridSize))) { return; }
    ivec3 last = textureSize(densityField, 0) - ivec3(1);
    ivec3 below = clamp(face - ivec3(0, 0, 1), ivec3(0), last);
    ivec3 above = clamp(face, ivec3(0), last);
    float rho = 0.5 * (texelFetch(densityField, below, 0).r + texelFetch(densityField, above, 0).r);
    float theta = 0.5 * (texelFetch(temperatureField, below, 0).r + texelFetch(temperatureField, above, 0).r);
    float w = texelFetch(inputField, face, 0).r;
    float a = thermalLift * theta - densityWeight * rho;
    imageStore(outputField, face, vec4(w + dt * a, 0.0, 0.0, 1.0));
}
