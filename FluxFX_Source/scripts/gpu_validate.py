"""Run in a fresh graphical Blender process; writes JSON and exits.

blender --factory-startup --python scripts/gpu_validate.py -- --output /tmp/fluxfx.json
Do not use --background: it cannot validate Blender's interactive gpu module.
"""
import argparse
import json
import math
from pathlib import Path
import sys
import traceback

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run_suite():
    from fluxfx.backend.diagnostics import collect
    from fluxfx.backend.dense import DenseAdvection
    from fluxfx.physics.config import GridSpec, AdvectionSettings
    from fluxfx.physics.reference import advect

    report = {"diagnostics": collect(run_probe=True), "tests": []}
    if report["diagnostics"]["status"] != "READY":
        raise RuntimeError(json.dumps(report["diagnostics"]))
    grid = GridSpec((9, 7, 5))
    initial = [((x * 13 + y * 7 + z * 3) % 17) / 17
               for z in range(5) for y in range(7) for x in range(9)]

    def compare(name, settings, steps, dt=0.04):
        solver = DenseAdvection(grid, settings)
        try:
            solver.upload(initial)
            expected = initial
            for _ in range(steps):
                expected = advect(expected, grid, settings, dt)
                solver.step(dt)
            actual = solver.read_density()
            error = max(abs(a - b) for a, b in zip(actual, expected))
            assert all(math.isfinite(a) and a >= 0 for a in actual), name
            assert error < 2e-5, (name, error)
            report["tests"].append({"name": name, "status": "PASS", "max_abs_error": error, "steps": steps})
        finally:
            solver.close()

    compare("zero_velocity_identity", AdvectionSettings(velocity=(0, 0, 0), angular_speed=0,
                                                        source_rate=0, dissipation=0), 2)
    compare("translation_open_boundary", AdvectionSettings(velocity=(0.2, -0.3, 0.4), angular_speed=0,
                                                            source_rate=0, dissipation=0), 4)
    compare("rotation_source_decay", AdvectionSettings(source_radius=0.3), 8)
    compare("decay_only", AdvectionSettings(velocity=(0, 0, 0), angular_speed=0,
                                            source_rate=0, dissipation=0.7), 3)
    # Multiple dependent dispatches with no intermediate readbacks exercise barriers.
    for resolution in (64, 128):
        solver = DenseAdvection(GridSpec((resolution,) * 3))
        try:
            seed = solver.read_density()
            for _ in range(30):
                solver.step()
            field = solver.read_density()
            assert all(math.isfinite(v) and v >= 0 for v in field)
            assert max(field) > 0 and field != seed
            solver.reset()
            assert solver.read_density() == seed
            solver.reset(seed=False)
            assert not any(solver.read_density())
            report["tests"].append({"name": f"dense_{resolution}_30_steps_and_reset", "status": "PASS",
                                    "density_bytes": solver.grid.density_bytes, "max_density": max(field)})
        finally:
            solver.close()
    import fluxfx
    for _ in range(2):
        fluxfx.register()
        assert hasattr(bpy.types.Scene, "fluxfx")
        fluxfx.unregister()
        assert not hasattr(bpy.types.Scene, "fluxfx")
    report["tests"].append({"name": "register_unregister_twice", "status": "PASS"})
    report["status"] = "PASS"
    return report


def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(ROOT / "test-results" / "gpu-validation.json"))
    options = parser.parse_args(args)
    output = Path(options.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    def execute():
        try:
            report = run_suite()
        except Exception:
            report = {"status": "FAIL", "traceback": traceback.format_exc()}
        output.write_text(json.dumps(report, indent=2) + "\n")
        print("FLUXFX_VALIDATION", json.dumps(report), flush=True)
        bpy.ops.wm.quit_blender()
        return None

    bpy.app.timers.register(execute, first_interval=1.0)


if __name__ == "__main__":
    main()
