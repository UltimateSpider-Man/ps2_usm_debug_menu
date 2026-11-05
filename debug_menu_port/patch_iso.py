"""Patch only the boot ELF in an existing, packed-asset USM PAL ISO.

usage: python patch_iso.py <original.iso> <new.iso> [--restore-amalga AMALGA.PAK]
File extents and directory records are preserved. Optional archive repair only
restores a zero-filled suffix after an identical prefix. The source and an
existing destination are never overwritten.
"""
import argparse
from contextlib import ExitStack
import os
from pathlib import Path
import re
import shutil
import tempfile

import patch_elf

SECTOR = 2048
BOOT_NAME = b'SLES_536.72;1'


def both_endian(data, offset, width):
    little = int.from_bytes(data[offset:offset + width], 'little')
    big = int.from_bytes(data[offset + width:offset + 2 * width], 'big')
    if little != big:
        raise ValueError('inconsistent ISO9660 numeric field')
    return little


def read_at(stream, offset, size):
    stream.seek(offset)
    data = stream.read(size)
    if len(data) != size:
        raise ValueError('truncated ISO image')
    return data


def record(data, volume_size):
    if len(data) < 34 or data[0] != len(data):
        raise ValueError('invalid ISO9660 directory record length')
    name_size = data[32]
    if not name_size or 33 + name_size + (name_size % 2 == 0) > len(data):
        raise ValueError('invalid ISO9660 file identifier')
    offset = both_endian(data, 2, 4) * SECTOR
    size = both_endian(data, 10, 4)
    if offset > volume_size or size > volume_size - offset:
        raise ValueError('ISO9660 extent exceeds the image volume')
    return dict(name=data[33:33 + name_size], offset=offset, size=size,
                flags=data[25], extended=data[1], interleaved=data[26:28])


def require_contiguous(entry, directory=False):
    if (bool(entry['flags'] & 2) != directory or entry['flags'] & 0x80
            or entry['extended'] or entry['interleaved'] != b'\0\0'):
        raise ValueError('unsupported ISO9660 extent for %r' % entry['name'])


def volume_root(stream, image_size):
    pvd = read_at(stream, 16 * SECTOR, SECTOR)
    if pvd[:7] != b'\x01CD001\x01':
        raise ValueError('expected a 2048-byte-sector ISO9660 primary volume')
    if both_endian(pvd, 128, 2) != SECTOR:
        raise ValueError('unsupported ISO logical block size')
    volume_size = both_endian(pvd, 80, 4) * SECTOR
    if volume_size < 17 * SECTOR or volume_size > image_size:
        raise ValueError('truncated or invalid ISO9660 volume')
    root = record(pvd[156:156 + pvd[156]], volume_size)
    require_contiguous(root, directory=True)
    if root['name'] != b'\0' or not root['size']:
        raise ValueError('invalid ISO9660 root directory')
    return root, volume_size


def directory_entries(stream, directory, volume_size):
    require_contiguous(directory, directory=True)
    entries = {}
    for block in range(0, directory['size'], SECTOR):
        data = read_at(stream, directory['offset'] + block,
                       min(SECTOR, directory['size'] - block))
        pos = 0
        while pos < len(data) and data[pos]:
            length = data[pos]
            if length > len(data) - pos:
                raise ValueError('directory record crosses a sector boundary')
            item = record(data[pos:pos + length], volume_size)
            if item['name'] in entries:
                raise ValueError('duplicate ISO directory file identifier')
            entries[item['name']] = item
            pos += length
    return entries


def boot_extent(stream, image_size):
    root, volume_size = volume_root(stream, image_size)
    entries = directory_entries(stream, root, volume_size)
    if b'SYSTEM.CNF;1' not in entries or BOOT_NAME not in entries:
        raise ValueError('expected SYSTEM.CNF;1 and SLES_536.72;1 in ISO root')
    config, boot = entries[b'SYSTEM.CNF;1'], entries[BOOT_NAME]
    require_contiguous(config)
    require_contiguous(boot)
    if not 0 < config['size'] <= SECTOR:
        raise ValueError('unexpected SYSTEM.CNF size')
    cnf = read_at(stream, config['offset'], config['size'])
    if not re.search(rb'(?im)^\s*BOOT2\s*=\s*cdrom0:\\SLES_536\.72;1\s*$', cnf):
        raise ValueError('SYSTEM.CNF does not boot the supported PAL ELF')
    if boot['size'] != 6960960:
        raise ValueError('unexpected SLES_536.72 size')
    boot_end = boot['offset'] + boot['size']
    if boot['offset'] < 17 * SECTOR:
        raise ValueError('boot ELF overlaps ISO volume descriptors')
    for item in entries.values():
        if item is not boot and item['size']:
            if boot['offset'] < item['offset'] + item['size'] and item['offset'] < boot_end:
                raise ValueError('boot ELF overlaps another ISO root extent')
    return boot


def amalgam_extent(stream, image_size):
    root, volume_size = volume_root(stream, image_size)
    root_entries = directory_entries(stream, root, volume_size)
    if b'PACKS' not in root_entries:
        raise ValueError('expected PACKS directory for archive restoration')
    pack_entries = directory_entries(stream, root_entries[b'PACKS'], volume_size)
    if b'AMALGA.PAK;1' not in pack_entries:
        raise ValueError('expected PACKS/AMALGA.PAK;1 for archive restoration')
    archive = pack_entries[b'AMALGA.PAK;1']
    require_contiguous(archive)
    if not archive['size'] or archive['offset'] < 17 * SECTOR:
        raise ValueError('invalid AMALGA.PAK extent')
    for other in [root, *root_entries.values(), *pack_entries.values()]:
        if other is not archive and other['size']:
            if (archive['offset'] < other['offset'] + other['size']
                    and other['offset'] < archive['offset'] + archive['size']):
                raise ValueError('AMALGA.PAK overlaps another ISO extent')
    return archive


def zero_suffix_start(stream, archive, replacement):
    if os.fstat(replacement.fileno()).st_size != archive['size']:
        raise ValueError('replacement AMALGA.PAK must have the same size')
    first_difference = archive['size']
    for pos in range(0, archive['size'], 1024 * 1024):
        size = min(1024 * 1024, archive['size'] - pos)
        current = read_at(stream, archive['offset'] + pos, size)
        donor = read_at(replacement, pos, size)
        start = 0
        if first_difference == archive['size']:
            if current == donor:
                continue
            start = next(i for i, (a, b) in enumerate(zip(current, donor)) if a != b)
            first_difference = pos + start
            if first_difference < 32:
                raise ValueError('AMALGA.PAK header does not match the replacement')
        suffix = current[start:]
        if suffix != bytes(len(suffix)):
            raise ValueError('AMALGA.PAK differs in nonzero data; refusing archive restoration')
    return first_difference


def main(src, dst, restore_amalgam=None):
    src, dst = Path(src).resolve(), Path(dst).absolute()
    if src == dst.resolve() or os.path.lexists(dst):
        raise ValueError('destination must be a new file, different from the source')
    if not dst.parent.is_dir():
        raise ValueError('destination directory does not exist')
    temporary_iso = None
    restored = 0
    try:
        with src.open('rb') as source, ExitStack() as inputs:
            source_size = os.fstat(source.fileno()).st_size
            boot = boot_extent(source, source_size)
            if restore_amalgam is not None:
                archive = amalgam_extent(source, source_size)
                replacement = inputs.enter_context(Path(restore_amalgam).open('rb'))
                restore_start = zero_suffix_start(source, archive, replacement)
                restored = archive['size'] - restore_start
            with tempfile.TemporaryDirectory(prefix='usm-elf-', dir=dst.parent) as work:
                original = Path(work) / 'SLES_536.72'
                patched = Path(work) / 'patched.elf'
                original.write_bytes(read_at(source, boot['offset'], boot['size']))
                patch_elf.main(original, patched)
                payload = patched.read_bytes()
            if len(payload) != boot['size']:
                raise ValueError('patched ELF changed size; ISO extents cannot be preserved')
            descriptor, name = tempfile.mkstemp(prefix=dst.name + '.', suffix='.tmp', dir=dst.parent)
            temporary_iso = Path(name)
            with os.fdopen(descriptor, 'w+b') as output:
                source.seek(0)
                shutil.copyfileobj(source, output, length=8 * 1024 * 1024)
                if output.tell() != source_size:
                    raise ValueError('source ISO size changed while copying')
                output.seek(boot['offset'])
                output.write(payload)
                if restored:
                    output.seek(archive['offset'] + restore_start)
                    for pos in range(restore_start, archive['size'], 1024 * 1024):
                        size = min(1024 * 1024, archive['size'] - pos)
                        output.write(read_at(replacement, pos, size))
                output.flush()
                os.fsync(output.fileno())
        if os.name == 'nt':
            os.rename(temporary_iso, dst)  # Windows refuses an existing destination.
        else:
            os.link(temporary_iso, dst)  # Publish without overwriting a raced destination.
            temporary_iso.unlink()
        temporary_iso = None
        print('written %s (%d bytes); boot ELF replaced' % (dst, source_size))
        if restore_amalgam is not None:
            print('AMALGA.PAK: %d bytes restored from the validated zero-filled suffix' % restored)
    finally:
        if temporary_iso is not None:
            temporary_iso.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_iso')
    parser.add_argument('destination_iso')
    parser.add_argument('--restore-amalga', metavar='AMALGA.PAK')
    args = parser.parse_args()
    try:
        main(args.source_iso, args.destination_iso, args.restore_amalga)
    except (OSError, ValueError, AssertionError) as error:
        raise SystemExit(str(error))
