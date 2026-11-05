r"""Build and verify the injected PAL debug-menu ELF using only Python.

Examples:
  python build_injected_elf.py "path\original.iso"
  python build_injected_elf.py "path\SLES_536.72" --output "out\SLES_536.72"
"""
import argparse
import hashlib
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parent
PORT = ROOT / 'debug_menu_port'
DEFAULT_SOURCE = ROOT / 'source' / 'SLES_536.72'
sys.path.insert(0, str(PORT))
import patch_elf
import patch_iso


def _publish_windows(payload, output):
    """Atomically publish without retaining TemporaryDirectory's private ACL.

    An ordinary exclusive sibling inherits the destination directory's ACL.
    Windows rename refuses an existing destination, including one that appears
    after the caller's existence check. Never use replace() here.
    """
    sibling = output.with_name('.%s.%s.tmp' % (output.name, uuid.uuid4().hex))
    created = False
    try:
        with sibling.open('xb') as stream:
            created = True
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.rename(sibling, output)
    finally:
        if created:
            sibling.unlink(missing_ok=True)


def build(source, output):
    if sys.flags.optimize:
        raise ValueError('run Python without -O; the patcher requires its validation checks')
    source, output = Path(source).resolve(), Path(output).absolute()
    if source == output.resolve():
        raise ValueError('source and output must be different files')
    with source.open('rb') as stream:
        if stream.read(4) == b'\x7fELF':
            stream.seek(0)
            original = stream.read()
        else:
            extent = patch_iso.boot_extent(stream, os.fstat(stream.fileno()).st_size)
            original = patch_iso.read_at(stream, extent['offset'], extent['size'])
    if len(original) != 6960960:
        raise ValueError('expected a clean PAL SLES_536.72 executable (6,960,960 bytes)')

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='usm-elf-build-', dir=output.parent) as work:
        clean = Path(work) / 'original.elf'
        injected = Path(work) / 'injected.elf'
        clean.write_bytes(original)
        print('Source: %s' % source, flush=True)
        try:
            patch_elf.main(clean, injected)
        except (AssertionError, struct.error) as error:
            raise ValueError('ELF validation failed; use a clean, supported PAL executable') from error
        result = subprocess.run(
            [sys.executable, '-E', str(PORT / 'test_dm.py'), str(injected)],
            capture_output=True, text=True)
        if result.returncode:
            print(result.stdout, end='')
            print(result.stderr, end='', file=sys.stderr)
            raise ValueError('injected ELF failed verification; output was not published')
        print('Verification: ALL TESTS PASSED')
        payload = injected.read_bytes()
        if len(payload) != len(original):
            raise ValueError('injected ELF changed size; output was not published')
        if os.path.lexists(output):
            if not output.is_file() or output.read_bytes() != payload:
                raise FileExistsError('output already exists with different contents: %s' % output)
            print('Already up to date: %s (existing file preserved)' % output)
        elif os.name == 'nt':
            _publish_windows(payload, output)
            print('Written: %s' % output)
        else:
            os.link(injected, output)  # Publish without replacing a raced destination.
            print('Written: %s' % output)
        print('Size: %d bytes; SHA-256: %s' % (len(payload), hashlib.sha256(payload).hexdigest()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', nargs='?', default=DEFAULT_SOURCE,
                        help='clean PAL ELF or original ISO (default: source/SLES_536.72)')
    parser.add_argument('--output', default=ROOT / 'out' / 'expanded' / 'SLES_536.72',
                        help='destination ELF (default: out/expanded/SLES_536.72 beside this script)')
    args = parser.parse_args()
    try:
        build(args.source, args.output)
    except (OSError, ValueError) as error:
        raise SystemExit(str(error))
