"""Build a Blender extension ZIP and a clean source ZIP (standard library only).

The version comes from fluxfx/blender_manifest.toml. The native core comes from
a fresh local build (fluxfx/native/, gitignored) when present, otherwise from
the provenance-verified prebuilt (see scripts/native_artifact.py).
"""
import argparse
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from fluxfx.version import VERSION  # noqa: E402
import native_artifact  # noqa: E402

NATIVE_ENTRY = "native/" + native_artifact.NAME


def eligible(path):
    return path.is_file() and not any(part in {
        ".git", "__pycache__", "dist", "test-results", "fluxfx-cache", ".DS_Store"
    } for part in path.relative_to(ROOT).parts) and path.suffix not in {".pyc", ".zip", ".log", ".fxc"}


def write_zip(destination, pairs):
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, name in sorted(pairs, key=lambda pair: pair[1]):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    print(destination)


def native_binary():
    if native_artifact.BUILT.is_file():
        print(f"Native core: local build {native_artifact.digest(native_artifact.BUILT)}")
        return native_artifact.BUILT
    binary = native_artifact.prebuilt_binary()
    print(f"Native core: verified prebuilt {native_artifact.digest(binary)}")
    return binary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    addon = ROOT / "fluxfx"
    try:
        binary = native_binary()
    except RuntimeError as exc:
        raise SystemExit(str(exc))
    extension = [(p, p.relative_to(addon).as_posix()) for p in addon.rglob("*")
                 if eligible(p) and p.suffix != ".so"]
    extension.append((binary, NATIVE_ENTRY))
    extension += [(ROOT / "LICENSE", "LICENSE"), (ROOT / "README.md", "README.md")]
    extension += [(p, p.relative_to(ROOT).as_posix()) for p in (ROOT / "docs").rglob("*") if eligible(p)]
    write_zip(args.out_dir / f"fluxfx-{VERSION}.zip", extension)
    source = [(p, "fluxfx/" + p.relative_to(ROOT).as_posix()) for p in ROOT.rglob("*") if eligible(p) and p.suffix != ".so"]
    write_zip(args.out_dir / f"fluxfx-source-{VERSION}.zip", source)


if __name__ == "__main__":
    main()
