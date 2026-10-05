// One texel per field slot (x): the largest magnitude in that field's last
// max_reduce level. NaN/Inf map to max_reduce's 3.4e38 sentinel, so a single
// tiny readback reveals an invalid value anywhere in any guarded field.
float fieldMax(sampler3D field)
{
    ivec3 size = textureSize(field, 0);
    float m = 0.0;
    for (int z = 0; z < size.z; ++z) {
        for (int y = 0; y < size.y; ++y) {
            for (int x = 0; x < size.x; ++x) {
                float v = texelFetch(field, ivec3(x, y, z), 0).r;
                m = max(m, (isnan(v) || isinf(v)) ? 3.4e38 : abs(v));
            }
        }
    }
    return m;
}

void main()
{
    ivec3 cell = ivec3(gl_GlobalInvocationID.xyz);
    if (any(greaterThanEqual(cell, gridSize))) { return; }
    float m;
    if (cell.x == 0) { m = fieldMax(field0); }
    else if (cell.x == 1) { m = fieldMax(field1); }
    else if (cell.x == 2) { m = fieldMax(field2); }
    else if (cell.x == 3) { m = fieldMax(field3); }
    else if (cell.x == 4) { m = fieldMax(field4); }
    else if (cell.x == 5) { m = fieldMax(field5); }
    else if (cell.x == 6) { m = fieldMax(field6); }
    else { m = fieldMax(field7); }
    imageStore(outputField, cell, vec4(m, 0.0, 0.0, 1.0));
}
