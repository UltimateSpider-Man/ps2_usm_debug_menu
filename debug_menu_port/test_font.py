"""Private-font asset and EE initialization contract checks (no emulator needed)."""
import hashlib
import re
import struct
import unittest
from asm5900 import Asm
from emu import Mem, CPU
import dm_font as F

GLOBAL, RETAIL, HEAP, TEXTURE, FONT = 0x6A02C4, 0x1100000, 0x1200000, 0x1300000, 0x1400000


def install_stubs(ctx):
    """Install into test_dm's fixture after its existing native stubs are ready.

    Its font constructor returns the fixture's FONT so existing measurement
    assertions remain useful. The isolated tests below verify private identity.
    """
    mem, cpu, A = (ctx[key] for key in ('mem', 'cpu', 'A'))
    fake_font = ctx['FONT']
    heap, texture = 0x01A00000, 0x01A10000
    previous_alloc = cpu.stubs.get(F.MEM_ALLOC)
    mem.write(heap, bytes(F.DECODED_SIZE + 16))
    mem.write(texture, bytes(0x100))

    def allocate(c):
        if c.r[4:7] == [0x58, 8, 0x1000000]:
            c.r[2] = fake_font
            return
        if c.r[4:7] != [F.DECODED_SIZE, 128, 0x1000000]:
            assert previous_alloc is not None, 'unexpected non-font allocation'
            return previous_alloc(c)
        c.r[2] = heap

    def load_texture(c):
        assert c.r[4:8] == [A.labels['dm_font_name'], 0, heap, F.TEXTURE_SIZE]
        assert hashlib.sha256(mem.read(heap, F.TEXTURE_SIZE)).hexdigest() == F.TEXTURE_SHA256
        mem.write(texture + 0x56, struct.pack('<HH', 256, 128))
        c.r[2] = texture

    def create_font(c):
        assert c.r[4:6] == [heap + F.TEXTURE_SIZE, fake_font]
        assert mem.u32(fake_font + 0x24) == texture
        assert hashlib.sha256(mem.read(c.r[4], F.FDF_SIZE)).hexdigest() == F.FDF_SHA256

    cpu.stubs.update({F.MEM_ALLOC: allocate, F.CONSTRUCT_TEXTURE: load_texture,
                      F.PARSE_FONT: create_font})


def fixture(allocation=True, texture=True, font=True):
    A = Asm(0xE0000)
    ctx = {'G': {'nglSysFont': GLOBAL}}
    F.emit_code(A, None, ctx); F.emit_data(A, None, ctx); F.emit_bss(A, ctx)
    blob = A.assemble()
    mem = Mem(); mem.write(A.base, blob)
    mem.write(0x1E00000, bytes(0x100000))
    mem.w32(GLOBAL, RETAIL)
    mem.write(HEAP, b'\xA5' * (F.DECODED_SIZE + 16))
    mem.write(TEXTURE, bytes(0x100)); mem.write(FONT, bytes(0x58))
    cpu = CPU(mem, A.base, A.pc)
    calls = []

    def alloc(c):
        if c.r[4:7] == [0x58, 8, 0x1000000]:
            calls.append('font_allocate')
            c.r[2] = FONT if font else 0
            return
        calls.append('allocate')
        assert c.r[4:7] == [F.DECODED_SIZE, 128, 0x1000000]
        c.r[2] = HEAP if allocation else 0

    def load(c):
        calls.append('texture')
        assert c.r[4:8] == [A.labels['dm_font_name'], 0, HEAP, F.TEXTURE_SIZE]
        assert mem.cstr(c.r[4] + 4) == F.NAME
        assert hashlib.sha256(mem.read(HEAP, F.TEXTURE_SIZE)).hexdigest() == F.TEXTURE_SHA256
        mem.write(TEXTURE + 0x56, struct.pack('<HH', 256 if texture else 16, 128))
        c.r[2] = TEXTURE

    def create(c):
        calls.append('font')
        assert c.r[4:6] == [HEAP + F.TEXTURE_SIZE, FONT]
        assert hashlib.sha256(mem.read(c.r[4], F.FDF_SIZE)).hexdigest() == F.FDF_SHA256
        assert mem.read(FONT, 32) == mem.read(A.labels['dm_font_name'], 32)
        assert mem.u32(FONT + 0x20) == 1
        assert mem.u32(FONT + 0x24) == TEXTURE
        assert mem.u32(FONT + 0x40) == mem.u32(FONT + 0x44) == 2
        assert mem.u32(FONT + 0x28) == mem.u32(FONT + 0x4C) == 0

    cpu.stubs.update({F.MEM_ALLOC: alloc, F.CONSTRUCT_TEXTURE: load, F.PARSE_FONT: create})
    return A, mem, cpu, calls


class FontTests(unittest.TestCase):
    def test_reference_metrics(self):
        raw = F.unpack(F.asset())
        self.assertEqual(raw[:4], b'TIM2')
        text = raw[F.TEXTURE_SIZE:].decode('ascii')
        self.assertIn('cellheight 15 ascent 12', text)
        self.assertIn('firstglyph 32 numglyphs 95', text)
        rows = re.findall(r'(\d+) x (\d+) y (\d+) w (\d+) gx (-?\d+) gy (-?\d+) gw (\d+) gh (\d+)', text)
        self.assertEqual([int(row[0]) for row in rows], list(range(32, 127)))
        self.assertEqual({int(row[3]) for row in rows}, {10})
        self.assertEqual(F.unpack(F.pack(raw)), raw)

    def test_machine_decoder_and_private_initialization(self):
        A, mem, cpu, calls = fixture()
        self.assertEqual(cpu.call(A.labels['dm_font_init']), FONT)
        self.assertEqual(mem.read(HEAP, F.DECODED_SIZE), F.unpack(F.asset()))
        self.assertEqual(mem.read(HEAP + F.DECODED_SIZE, 16), b'\xA5' * 16)
        self.assertEqual(mem.u32(GLOBAL), RETAIL)
        self.assertEqual(mem.u32(A.labels['dm_menu_font']), FONT)
        self.assertEqual(mem.u32(A.labels['dm_font_stage']), F.STAGE_READY)
        self.assertEqual(mem.u32(A.labels['dm_font_texture']), TEXTURE)
        self.assertEqual(mem.u32(FONT + 0x50), 1)
        self.assertEqual(mem.u64(TEXTURE + 0x68), 2)
        self.assertEqual(cpu.call(A.labels['dm_font_get']), FONT)
        self.assertEqual(cpu.call(A.labels['dm_font_init']), FONT)
        self.assertEqual(calls, ['allocate', 'texture', 'font_allocate', 'font'])
        self.assertNotIn(0x596230, cpu.trace_calls)
        self.assertNotIn(0x592B84, cpu.trace_calls)

    def test_waits_for_native_renderer(self):
        A, mem, cpu, calls = fixture()
        mem.w32(GLOBAL, 0)
        self.assertEqual(cpu.call(A.labels['dm_font_init']), 0)
        self.assertEqual(mem.u32(A.labels['dm_font_attempted']), 0)
        self.assertEqual(mem.u32(A.labels['dm_font_stage']), 0)
        self.assertEqual(calls, [])
        mem.w32(GLOBAL, RETAIL)
        self.assertEqual(cpu.call(A.labels['dm_font_init']), FONT)

    def test_failure_falls_back_once_without_global_changes(self):
        for options, expected, stage in [({'allocation': False}, ['allocate'], F.STAGE_ALLOCATE),
                                         ({'texture': False}, ['allocate', 'texture'], F.STAGE_DIMENSIONS),
                                         ({'font': False}, ['allocate', 'texture', 'font_allocate'], F.STAGE_CREATE)]:
            with self.subTest(options=options):
                A, mem, cpu, calls = fixture(**options)
                self.assertEqual(cpu.call(A.labels['dm_font_init']), RETAIL)
                self.assertEqual(cpu.call(A.labels['dm_font_init']), RETAIL)
                self.assertEqual(cpu.call(A.labels['dm_font_get']), RETAIL)
                self.assertEqual(calls, expected)
                self.assertEqual(mem.u32(GLOBAL), RETAIL)
                self.assertEqual(mem.u32(A.labels['dm_menu_font']), 0)
                self.assertEqual(mem.u32(A.labels['dm_font_stage']), stage)


if __name__ == '__main__':
    unittest.main()
