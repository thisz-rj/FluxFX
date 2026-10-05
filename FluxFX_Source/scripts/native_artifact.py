"""Verify, install or record the prebuilt native core.

The compiled module is a build artifact, not source. `prebuilt/<platform>/
PROVENANCE.json` records the SHA-256 of the binary and of every native source
file it was compiled from. A prebuilt is usable only while those sources are
unchanged; after editing native code, rebuild with `build_native.py` and run
`record` to refresh the artifact and its provenance together.

    python3 scripts/native_artifact.py verify    # CI: prebuilt matches sources
    python3 scripts/native_artifact.py install   # copy prebuilt into fluxfx/native
    python3 scripts/native_artifact.py record    # after build_native.py (macOS)
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
PLATFORM = "macos-arm64"
PREBUILT = ROOT / "prebuilt" / PLATFORM
PROVENANCE = PREBUILT / "PROVENANCE.json"
NAME = "fluxfx_core.abi3.so"
BUILT = ROOT / "fluxfx" / "native" / NAME


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def build_inputs():
    """Every file compiled or included into the module; CPU tests excluded."""
    native = ROOT / "native"
    files = [p for p in native.iterdir()
             if p.suffix in {".cpp", ".mm", ".hpp", ".inc"} and not p.stem.endswith("_test")]
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(files)}


def load():
    return json.loads(PROVENANCE.read_text(encoding="utf-8"))


def problems():
    """Empty when the prebuilt binary is present and matches current sources."""
    if not PROVENANCE.is_file():
        return [f"Missing {PROVENANCE.relative_to(ROOT)}"]
    record = load()
    binary = PREBUILT / record["artifact"]
    found = []
    if not binary.is_file():
        found.append(f"Missing prebuilt binary {binary.relative_to(ROOT)}")
    elif digest(binary) != record["sha256"]:
        found.append("Prebuilt binary does not match its recorded SHA-256")
    current, recorded = build_inputs(), record["sources"]
    for name in sorted(set(current) | set(recorded)):
        if current.get(name) != recorded.get(name):
            state = "added" if name not in recorded else "removed" if name not in current else "changed"
            found.append(f"Native source {state} since the prebuilt was built: {name}")
    return found


def prebuilt_binary():
    """Path to a verified prebuilt; raises with every mismatch otherwise."""
    issues = problems()
    if issues:
        raise RuntimeError("Prebuilt native core is unusable:\n  " + "\n  ".join(issues) +
                           "\nRebuild with scripts/build_native.py, then run scripts/native_artifact.py record.")
    return PREBUILT / load()["artifact"]


def record(evidence=None):
    if not BUILT.is_file():
        raise SystemExit(f"Build first: {BUILT.relative_to(ROOT)} is missing (scripts/build_native.py)")
    PREBUILT.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(BUILT, PREBUILT / NAME)
    previous = load() if PROVENANCE.is_file() else {}
    data = dict(previous, artifact=NAME, platform=PLATFORM, sha256=digest(BUILT), sources=build_inputs(),
                built_by="scripts/build_native.py")
    if evidence:
        data["evidence"] = evidence
    PROVENANCE.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Recorded {NAME} {data['sha256']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("verify", "install", "record"))
    parser.add_argument("--evidence", help="record: validation folder proving this build")
    args = parser.parse_args()
    if args.action == "verify":
        issues = problems()
        for issue in issues:
            print("FAIL:", issue)
        if issues:
            sys.exit(1)
        print(f"Prebuilt {PLATFORM} native core matches {len(load()['sources'])} source files")
    elif args.action == "install":
        source = prebuilt_binary()
        shutil.copyfile(source, BUILT)
        print(f"Installed {BUILT.relative_to(ROOT)}")
    else:
        record(args.evidence)


if __name__ == "__main__":
    main()
