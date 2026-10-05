"""Build the arm64 stable-ABI extension using local Xcode headers and Metal SDK."""
import argparse
import platform
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--python-include',type=Path)
    args=parser.parse_args()
    if platform.system()!='Darwin' or platform.machine()!='arm64':
        raise SystemExit('P1.2 build requires macOS Apple Silicon')
    developer=Path(subprocess.check_output(['xcode-select','-p'],text=True).strip())
    headers=args.python_include or developer/'Library/Frameworks/Python3.framework/Versions/3.9/Headers'
    if not (headers/'Python.h').is_file():
        raise SystemExit('Python development headers missing; pass --python-include PATH (Python 3.9 or newer)')
    target=ROOT/'fluxfx/native/fluxfx_core.abi3.so'
    temp=target.with_suffix('.tmp.so')
    try:
        subprocess.run(['xcrun','clang++','-std=c++17','-O2','-Wall','-Wextra',
            '-Werror','-Wno-missing-field-initializers','-arch','arm64','-mmacosx-version-min=13.0',
            '-fobjc-arc','-bundle','-undefined','dynamic_lookup','-I'+str(headers),
            str(ROOT/'native/module.cpp'),str(ROOT/'native/core.mm'),str(ROOT/'native/resources.mm'),str(ROOT/'native/transport.mm'),str(ROOT/'native/mac.mm'),str(ROOT/'native/projection.mm'),
            '-framework','Foundation','-framework','Metal','-o',str(temp)],check=True)
        temp.replace(target)
    finally:
        if temp.exists():temp.unlink()
    print(target)

if __name__=='__main__':main()
