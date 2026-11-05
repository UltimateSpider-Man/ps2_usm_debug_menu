"""Injects the debug menu into SLES_536.72.

usage: patch_elf.py <original SLES_536.72> <output path>

The output file has exactly the same size as the input. The menu is mapped by
a second PT_LOAD segment at 0xE0000, in user RAM below the game image, so the
game's own memory layout (BSS, heap, stack) is unchanged. Its file data is
stored in the non-loaded .DVP.overlay link data. Every patch site is verified
against the original instruction before being changed.
"""
import struct, sys, hashlib
import dm_build as D

SEG0_VADDR, SEG0_OFF = 0x100000, 0x1000
PAYLOAD_OFF = 0x64D000      # inside .DVP.overlay data, congruent to BASE mod 0x1000
DVP_LO, DVP_HI = 0x64B49B, 0x69F60B   # first overlay section .. start of .shstrtab


def jal(t):
    return 0x0C000000 | ((t >> 2) & 0x3ffffff)


def main(src, dst):
    data = bytearray(open(src, 'rb').read())
    size0 = len(data)
    A, blob = D.build()
    L = A.labels
    # fully file-backed: not every PS2 ELF loader zero-fills memsz beyond filesz
    filesz = memsz = L['dm_end'] - D.BASE
    assert len(blob) == memsz

    def off(va):
        return va - SEG0_VADDR + SEG0_OFF

    def patch(va, old, new, what):
        o = off(va)
        cur = struct.unpack_from('<I', data, o)[0]
        if cur != old:
            raise SystemExit('unexpected word %08x at %08x (%s), expected %08x - wrong input file?' % (cur, va, what, old))
        struct.pack_into('<I', data, o, new)
        print('  %08x: %08x -> %08x  %s' % (va, old, new, what))

    # ELF header sanity
    ident, etype, emach, ever, entry, phoff, shoff, flags, ehsize, phentsize, phnum = struct.unpack_from('<16sHHIIIIIHHH', data, 0)
    assert ident[:4] == b'\x7fELF' and emach == 8 and phnum == 1 and phoff == 0x34 and phentsize == 32
    p0 = struct.unpack_from('<8I', data, phoff)
    assert p0[:6] == (1, 0x1000, 0x100000, 0x100000, 0x647B9C, 0x671C60), p0
    assert data[0x54:0x74] == bytes(32), 'program header slot not free'
    assert D.BASE + memsz <= p0[2], 'menu overlaps the game image'

    print('hooks')
    patch(0x311DAC, jal(D.G['link_system_frame_advance']), jal(L['hook_tick']), 'app::tick -> debug menu frame advance')
    patch(0x295B78, jal(D.G['nglListEndScene']), jal(L['hook_render']), 'game::render_ui -> debug menu render')
    patch(0x37E09C, jal(D.G['get_control_delta']), jal(L['hook_pause']), 'IGOFrontEnd::CheckPauseUnpause pause read')
    patch(0x381254, jal(D.G['igo_zoom_map_on_select']), jal(L['hook_map']), 'IGOZoomOutMap::OnSelectPress call')
    patch(D.dm_slf.CALL_SITE, jal(D.dm_slf.NATIVE_CALL), jal(L['hook_slf_call']),
          'vm_thread::call_script_library_function -> optional recall-timeout report')

    # new PT_LOAD for the menu
    assert PAYLOAD_OFF % 0x1000 == D.BASE % 0x1000
    assert DVP_LO <= PAYLOAD_OFF and PAYLOAD_OFF + filesz <= DVP_HI, 'payload does not fit in the unused area'
    struct.pack_into('<8I', data, phoff + 32, 1, PAYLOAD_OFF, D.BASE, D.BASE, filesz, memsz, 7, 0x1000)
    struct.pack_into('<H', data, 0x2C, 2)
    data[PAYLOAD_OFF:PAYLOAD_OFF + filesz] = blob[:filesz]
    print('segment: vaddr %08x-%08x (filesz=memsz %x) file offset %x' % (D.BASE, D.BASE + memsz, memsz, PAYLOAD_OFF))
    assert len(data) == size0
    # the game's loaded image must differ from the original only at the hook sites
    orig = open(src, 'rb').read()
    seg = slice(SEG0_OFF, SEG0_OFF + p0[4])
    diff = [SEG0_VADDR + i - SEG0_OFF for i in range(seg.start, seg.stop, 4) if data[i:i + 4] != orig[i:i + 4]]
    assert diff == [0x295B78, D.dm_slf.CALL_SITE, 0x311DAC, 0x37E09C, 0x381254], ['%x' % x for x in diff]
    open(dst, 'wb').write(data)
    print('written %s (%d bytes, sha1 %s)' % (dst, len(data), hashlib.sha1(data).hexdigest()))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
