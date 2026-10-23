#!/usr/bin/env python3
"""Compile the generic platform expert against the actual source-kernel ABI."""
import argparse
import json
import shutil
import sys
from pathlib import Path
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('component', choices=['ArmVirtPlatform', 'ArmDTPlatform', 'ArmCpu', 'NativeAES', 'NativeVirtioBlock', 'NativeRamBlock', 'NativeMobileDisplay', 'NativeVirtioConsole', 'NativeLegacyDisplay', 'NativeGOPPresenter', 'NativeOfflineGPU', 'NativeOfflineAccelerator', 'NativeIOGPUProviderProbe', 'NativeUfs', 'NativeHidInput', 'NativeKeyStoreEvents', 'NativeAdreno'])
parser.add_argument('--negative-aes-kat', action='store_true', help='Isolated own-source wrong-answer refusal control; never changes original inputs')
parser.add_argument('--verified-root', action='store_true', help='Authenticate all actual disk reads against an independently signed immutable policy')
parser.add_argument('--verified-root-bundle', action='store_true', help='Select exactly one capacity-matching policy per device, then independently authenticate it')
parser.add_argument('--negative-verified-block', action='store_true', help='Negative own-buffer control: corrupt only the completed DMA snapshot')
args = parser.parse_args()
if args.verified_root_bundle and not args.verified_root:
    parser.error('A policy bundle requires verified block mode')
if args.verified_root_bundle and args.negative_verified_block:
    parser.error('Select either bundle policy qualification or the isolated DMA snapshot fault')
if (args.verified_root or args.negative_verified_block) and args.component != 'NativeVirtioBlock':
    parser.error('Verified block mode requires the concrete read-only block transport')
if args.negative_verified_block and not args.verified_root:
    parser.error('The isolated input fault requires verified block mode')
component = args.component
recipe = ROOT / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json'
record = json.loads(recipe.read_text().strip().rstrip(','))
source = ROOT / 'drivers' / ('NativeMobileDisplay' if component in ('NativeLegacyDisplay','NativeGOPPresenter') else 'NativeMetal' if component in ('NativeOfflineGPU','NativeOfflineAccelerator','NativeIOGPUProviderProbe') else component) / {'NativeAdreno':'NativeAdrenoService.cpp'}.get(component, component + '.cpp')
out = ROOT / 'build' / {'ArmVirtPlatform': 'armvirt-platform', 'ArmDTPlatform': 'armdt-platform', 'ArmCpu': 'armcpu', 'NativeAES': 'native-aes',
                        'NativeVirtioBlock': 'native-virtio-block', 'NativeRamBlock': 'native-ram-block',
                        'NativeMobileDisplay': 'native-mobile-display', 'NativeVirtioConsole': 'native-virtio-console',
                        'NativeLegacyDisplay': 'native-legacy-display', 'NativeGOPPresenter': 'native-gop-presenter', 'NativeOfflineGPU':'native-offline-gpu','NativeOfflineAccelerator':'native-offline-accelerator','NativeIOGPUProviderProbe':'native-original-provider', 'NativeUfs':'native-ufs', 'NativeHidInput':'native-hid-input', 'NativeKeyStoreEvents':'native-keystore-events', 'NativeAdreno':'native-adreno'}[component]
if args.verified_root:
    out = ROOT / ('build/native-virtio-block-verified-fault' if args.negative_verified_block else 'build/native-virtio-block-verified')
    if args.verified_root_bundle:
        out = ROOT / 'build/native-virtio-block-verified-bundle'
out.mkdir(parents=True, exist_ok=True)
if args.negative_aes_kat:
    if component != 'NativeAES':
        parser.error('The own-source KAT control requires NativeAES')
    out = ROOT / 'build/native-aes-kat-negative'
    out.mkdir(parents=True, exist_ok=True)
    text = source.read_text()
    marker = '0x76,0x49,0xab,0xac'
    if text.count(marker) != 1:
        raise SystemExit('The exact own-source NIST answer was not uniquely identified')
    (out / 'OriginalAESABI.h').write_bytes(source.with_name('OriginalAESABI.h').read_bytes())
    source = out / 'NativeAES.cpp'
    source.write_text(text.replace(marker, '0x77,0x49,0xab,0xac'))
destination = out / (component + '.o')
arguments = record['arguments']
command = []
index = 0
while index < len(arguments):
    value = arguments[index]
    if value == record['file']:
        command.append(str(source))
    elif value == '-o':
        command.extend(['-o', str(destination)])
        index += 1
    elif value == '-Xclang' and arguments[index + 1].startswith('-W'):
        index += 1
    elif not value.startswith('-W'):
        command.append(value)
    index += 1
command.extend(['-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                '-Wno-c99-designator', '-Wno-reorder-init-list', '-Wno-deprecated-enum-enum-conversion',
                '-Wno-unnecessary-virtual-specifier', '-I', str(ROOT / '.cache/xnu-work/osfmk')])
if component in ('NativeVirtioBlock', 'NativeRamBlock', 'NativeUfs'):
    command += ['-I', str(ROOT / 'build/storage-abi/include')]
    if args.verified_root:
        command += ['-I', str(ROOT / 'kits/VerifiedRoot/include'), '-DNATIVE_VERIFIED_BLOCK=1']
    if args.negative_verified_block:
        command += ['-DNATIVE_VERIFIED_BLOCK_INJECT_FAULT=1']
    if args.verified_root_bundle:
        command += ['-DNATIVE_VERIFIED_BLOCK_MULTI_POLICY=1']
# cas is SM8250: rewrite the driver SM8550 GCC register offsets with the SM8250 ones, transcribed from the
# halt_reg of each UFS branch in the public Linux gcc-sm8250.c clock driver. Both SoCs put the UFS PHY block at 0x77000.
if component == 'NativeUfs':
    gcc_header = ROOT / 'drivers/NativeUfs/GccUfs.h'
    gcc_text = gcc_header.read_text()
    for macro, value in (('GCC_UFS_PHY_AXI_ENABLE', 0x77010), ('GCC_UFS_PHY_AHB_ENABLE', 0x77018),
                         ('GCC_UFS_PHY_TX_SYMBOL0_ENABLE', 0x7701C), ('GCC_UFS_PHY_RX_SYMBOL0_ENABLE', 0x77020),
                         ('GCC_UFS_PHY_UNIPRO_CORE_ENABLE', 0x7705C), ('GCC_UFS_PHY_ICE_CORE_ENABLE', 0x77064),
                         ('GCC_UFS_PHY_PHY_AUX_ENABLE', 0x7709C), ('GCC_UFS_PHY_RX_SYMBOL1_ENABLE', 0x770B8),
                         ('GCC_AGGRE_UFS_PHY_AXI_ENABLE', 0x770CC)):
        lines = gcc_text.splitlines(True)
        for index, line in enumerate(lines):
            if line.startswith('#define ' + macro + ' '):
                lines[index] = '#define %s 0x%05x\n' % (macro, value)
        gcc_text = ''.join(lines)
    gcc_header.write_text(gcc_text)
    # Upstream oversight: read() uses timerTicks() and native_ufs_read_ticks, defined only inside the
    # NATIVE_VERIFIED_BLOCK block. sheng always defines it; a plain-mode build needs this guard.
    ufs_source = ROOT / 'drivers/NativeUfs/NativeUfs.cpp'
    ufs_text = ufs_source.read_text()
    old_read = ('      uint64_t t0 = timerTicks ();\n'
                '      IOReturn r = hostRead4k (0, lba, blocks, out);\n'
                '      __atomic_fetch_add (&native_ufs_read_ticks, timerTicks () - t0, __ATOMIC_RELAXED);')
    new_read = ('#if defined(NATIVE_VERIFIED_BLOCK) && NATIVE_VERIFIED_BLOCK\n'
                '      uint64_t t0 = timerTicks ();\n'
                '      IOReturn r = hostRead4k (0, lba, blocks, out);\n'
                '      __atomic_fetch_add (&native_ufs_read_ticks, timerTicks () - t0, __ATOMIC_RELAXED);\n'
                '#else\n'
                '      IOReturn r = hostRead4k (0, lba, blocks, out);\n'
                '#endif')
    if ufs_text.count(old_read) != 1:
        raise SystemExit('The NativeUfs read() timing block was not uniquely identified; refusing to patch')
    ufs_source.write_text(ufs_text.replace(old_read, new_read))
    print('NativeUfs: read() timing wrapped in the verified-block guard')
    if '0x77010' not in gcc_header.read_text():
        raise SystemExit('The SM8250 GCC offsets were not applied to drivers/NativeUfs/GccUfs.h')
    print('NativeUfs: SM8250 GCC offsets applied')
if component == 'NativeUfs':
    command += ['-I', str(ROOT / 'kits/VerifiedRoot/include'), '-I', str(ROOT / 'drivers/NativeVirtioBlock'),
                '-mgeneral-regs-only']  # cas has no verified-root chain yet: plain mode
if component=='NativeOfflineGPU':
    command += ['-I',str(ROOT/'drivers/NativeVirtioConsole')]
if component in ('NativeLegacyDisplay','NativeHidInput'):
    command += ['-I', str(out)]
if component == 'NativeAdreno':
    command += ['-I', str(ROOT / 'kits/ArmSmmu4K'), '-I', str(ROOT / 'kits/AdrenoPM4'),
                '-I', str(ROOT / 'kits/sheng'), '-I', str(ROOT / 'kits/AdrenoFirmware'),
                '-I', str(ROOT / 'build/sheng-gmu')]
(out / 'compile-command.json').write_text(json.dumps(command, indent=2) + '\n')
result = subprocess.run(command, cwd=record['directory'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
(out / 'compile.log').write_text(result.stdout)
if result.returncode:
    errors = [line for line in result.stdout.splitlines() if ' error: ' in line]
    fatal = [line for line in result.stdout.splitlines() if line.endswith('errors generated.')]
    raise SystemExit('\\n'.join(errors[:25] + fatal) or result.stdout[-3500:])
data = destination.read_bytes()
magic, cpu, subtype, kind, count, size = struct.unpack_from('<6I', data)
if (magic, cpu, subtype, kind) != (0xfeedfacf, 0x100000c, 0, 1):
    raise SystemExit('Unexpected platform object architecture')
offset = 32
deployment = None
for _ in range(count):
    cmd, length = struct.unpack_from('<II', data, offset)
    if cmd == 0x32:
        deployment = struct.unpack_from('<II', data, offset + 8)
    offset += length
if deployment != (2, 0x110000):
    raise SystemExit(f'Unexpected platform deployment {deployment}')
archive = out / ('lib' + component + '.a')
archive.unlink(missing_ok=True)
subprocess.run(['xcrun', 'ar', 'rcs', archive, destination], check=True)
if component == 'NativeUfs':
    blob = None
    for base in (ROOT, ROOT.parents[1], ROOT.parents[2]):
        found = sorted(base.glob('ipsw/*/kernelcache.decompressed'))
        if found:
            blob = found[-1].read_bytes()
            break
    if blob is None:
        print('NativeUfs: no kernelcache yet; skipping the storage binding')
    else:
        sys.path.insert(0, str(ROOT / 'kits/NativePrelink'))
        import native_prelink as np
        exports = {}
        for va, names in np.exports(blob, np.macho(blob)).items():
            for name in names:
                exports[name] = va
        undefined = set()
        for line in subprocess.run(['llvm-nm', '-u', str(destination)], capture_output=True, text=True).stdout.splitlines():
            if line.strip():
                undefined.add(line.split()[-1])
        wanted = sorted(n for n in undefined if 'IOBlockStorageDevice' in n)
        missing = [n for n in wanted if n not in exports]
        if missing:
            raise SystemExit('NativeUfs: kernelcache lacks %s (%d exports)' % (', '.join(missing[:3]), len(exports)))
        asm = out / 'ufs-original-bindings.S'
        asm.write_text(''.join('.globl %s\n.set %s, %#x\n' % (n, n, exports[n]) for n in wanted))
        subprocess.run(['xcrun', 'clang', '-target', 'arm64-apple-ios17.0', '-Werror', '-Wno-incompatible-sysroot', '-c', str(asm), '-o', str(out / 'ufs-original-bindings.o')], check=True)
        archive.unlink(missing_ok=True)
        subprocess.run(['xcrun', 'ar', 'rcs', str(archive), str(destination), str(out / 'ufs-original-bindings.o')], check=True)
        print('NativeUfs: bound %d original storage symbols' % len(wanted))print(f'{component}: -Werror build and actual ARM64/iOS 17 object audit passed')
