#!/usr/bin/env python3
"""Bind the unsupplied original IOBlockStorageDevice symbols of libNativeUfs.a to the original kernelcache."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/native-ufs'
OBJ = OUT / 'NativeUfs.o'
ARCHIVE = OUT / 'libNativeUfs.a'
CACHE = ROOT / '.cache/firmware/kernelcache.macho/kernelcache.release.ipad7.decompressed'


def nm(path, *extra):
    tool = shutil.which('llvm-nm') or '/opt/homebrew/opt/llvm/bin/llvm-nm'
    return subprocess.run([tool, *extra, str(path)], capture_output=True, text=True, check=True).stdout


if not OBJ.is_file():
    raise SystemExit(str(OBJ) + ' is missing; build-arm-driver.py NativeUfs must run first')
undefined = set()
for line in nm(OBJ, '-u').splitlines():
    line = line.strip()
    if line:
        undefined.add(line.split()[-1])
wanted = sorted(name for name in undefined if 'IOBlockStorageDevice' in name)
if not wanted:
    print('NativeUfs: no unsupplied IOBlockStorageDevice imports; nothing to bind')
    raise SystemExit(0)
if CACHE.is_file():
    kernel = CACHE
else:
    cached = sorted(ROOT.parents[1].glob('ipsw/*/kernelcache.decompressed'))
    if not cached:
        # The bootstrap pass runs before the driver fetches the IPSW members, so the first pass cannot bind.
        # Its archive only serves that pass's tolerated link; the second pass binds for real.
        print('NativeUfs: no kernelcache yet (bootstrap pass); skipping the binding')
        raise SystemExit(0)
    kernel = cached[0]
defined = {}
for line in nm(kernel).splitlines():
    parts = line.split()
    if len(parts) == 3 and parts[1] in ('S', 's', 'T', 't', 'D', 'd', 'R', 'r', 'A'):
        defined[parts[2]] = int(parts[0], 16)
missing = [name for name in wanted if name not in defined]
if missing:
    raise SystemExit('Not in the original kernelcache: ' + ', '.join(missing))
assembly = OUT / 'ufs-original-bindings.S'
assembly.write_text(''.join('.globl %s\n.set %s, %#x\n' % (name, name, defined[name]) for name in wanted))
subprocess.run(['xcrun', 'clang', '-target', 'arm64-apple-ios17.0', '-Werror', '-Wno-incompatible-sysroot',
                '-c', str(assembly), '-o', str(OUT / 'ufs-original-bindings.o')], check=True)
ARCHIVE.unlink(missing_ok=True)
subprocess.run(['xcrun', 'ar', 'rcs', str(ARCHIVE), str(OBJ), str(OUT / 'ufs-original-bindings.o')], check=True)
(OUT / 'ufs-bindings.json').write_text(json.dumps(
    dict(kernelcache_sha256=hashlib.sha256(kernel.read_bytes()).hexdigest(),
         bound={name: hex(defined[name]) for name in wanted}, original_code_modified=False), indent=2) + '\n')
print('NativeUfs: bound %d original IOBlockStorageDevice symbols' % len(wanted))