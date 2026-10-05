"""Build a Blender extension ZIP and a clean source ZIP (standard library only)."""
import argparse
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.41.0"


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    addon = ROOT / "fluxfx"
    if not (addon / "native/fluxfx_core.abi3.so").is_file():
        raise SystemExit("Build the native core first: python3 scripts/build_native.py")
    extension = [(p, p.relative_to(addon).as_posix()) for p in addon.rglob("*") if eligible(p)]
    extension += [(ROOT / "LICENSE", "LICENSE"), (ROOT / "README.md", "README.md")]
    extension += [(p, p.relative_to(ROOT).as_posix()) for p in (ROOT / "docs").rglob("*") if eligible(p)]
    write_zip(args.out_dir / f"fluxfx-{VERSION}.zip", extension)
    source = [(p, "fluxfx/" + p.relative_to(ROOT).as_posix()) for p in ROOT.rglob("*") if eligible(p) and p.suffix != ".so"]
    write_zip(args.out_dir / f"fluxfx-source-{VERSION}.zip", source)


if __name__ == "__main__":
    main()
