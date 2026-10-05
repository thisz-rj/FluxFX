"""Every check that runs without graphical Blender; CI and local runs share it.

    python3 scripts/ci_checks.py               # all checks
    python3 scripts/ci_checks.py --skip-native # no C++ compiler available

Steps: byte-compile all Python, the standalone unit suite, the native CPU
tests (arena, bricks, regions), and prebuilt-binary provenance. Any failure
exits nonzero. GPU, Metal and Blender UI validation still need the graphical
scripts listed in README.md.
"""
import argparse
import compileall
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
NATIVE_TESTS = ("arena_test", "bricks_test", "regions_test")
CXX_FLAGS = ("-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", "-Wno-missing-field-initializers")


def step(name, action):
    start = time.perf_counter()
    print(f"== {name}", flush=True)
    ok = action()
    print(f"-- {name}: {'PASS' if ok else 'FAIL'} ({time.perf_counter() - start:.1f}s)", flush=True)
    return ok


def compile_python():
    return all(compileall.compile_dir(str(ROOT / folder), quiet=1, force=True)
               for folder in ("fluxfx", "tests", "scripts"))


def unit_tests():
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests"]
    return subprocess.run(command, cwd=ROOT).returncode == 0


def compiler(requested):
    for name in (requested, os.environ.get("CXX"), "c++", "clang++", "g++"):
        if name and shutil.which(name):
            return shutil.which(name)
    return None


def native_tests(cxx):
    with tempfile.TemporaryDirectory() as folder:
        for test in NATIVE_TESTS:
            binary = Path(folder) / test
            build = [cxx, *CXX_FLAGS, "-I", str(ROOT / "native"), str(ROOT / "native" / f"{test}.cpp"), "-o", str(binary)]
            if subprocess.run(build).returncode != 0:
                print(f"{test}: compile failed")
                return False
            if subprocess.run([str(binary)]).returncode != 0:
                print(f"{test}: failed")
                return False
    return True


def provenance():
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "native_artifact.py"), "verify"]).returncode == 0


def main():
    parser = argparse.ArgumentParser(description="FluxFX checks that run without graphical Blender")
    parser.add_argument("--skip-native", action="store_true", help="skip the C++ CPU tests")
    parser.add_argument("--cxx", help="C++ compiler (default: $CXX, c++, clang++, g++)")
    args = parser.parse_args()
    results = [step("compileall", compile_python), step("unit tests", unit_tests),
               step("prebuilt native provenance", provenance)]
    if not args.skip_native:
        cxx = compiler(args.cxx)
        if cxx is None:
            print("No C++ compiler found; pass --skip-native to run without native CPU tests")
            results.append(False)
        else:
            results.append(step(f"native CPU tests ({Path(cxx).name})", lambda: native_tests(cxx)))
    if not all(results):
        sys.exit(1)
    print("All checks passed")


if __name__ == "__main__":
    main()
