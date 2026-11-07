"""Tiny R5900 interpreter for testing the injected code against the real
SLES_536.72 image, with Python stubs standing in for game functions."""
import struct, re

M64 = (1 << 64) - 1


def sx32(v):
    v &= 0xffffffff
    return (v - (1 << 32)) & M64 if v & 0x80000000 else v


def s32(v):
    v &= 0xffffffff
    return v - (1 << 32) if v & 0x80000000 else v


def s64(v):
    v &= M64
    return v - (1 << 64) if v >> 63 else v


def f2b(f):
    return struct.unpack('<I', struct.pack('<f', f))[0]


def b2f(b):
    return struct.unpack('<f', struct.pack('<I', b & 0xffffffff))[0]


class Mem:
    PAGE = 0x10000

    def __init__(self):
        self.pages = {}

    def _p(self, a, create=True):
        k = a // self.PAGE
        p = self.pages.get(k)
        if p is None:
            if not create:
                raise MemoryError('read unmapped %08x' % a)
            p = self.pages[k] = bytearray(self.PAGE)
        return p, a % self.PAGE

    def write(self, a, data):
        for i, b in enumerate(data):
            p, o = self._p(a + i)
            p[o] = b

    def read(self, a, n):
        out = bytearray()
        for i in range(n):
            p, o = self._p(a + i, create=False)
            out.append(p[o])
        return bytes(out)

    def u8(self, a): return self.read(a, 1)[0]
    def u32(self, a):
        assert a % 4 == 0, 'unaligned lw %08x' % a
        return struct.unpack('<I', self.read(a, 4))[0]
    def u64(self, a):
        assert a % 8 == 0, 'unaligned ld %08x' % a
        return struct.unpack('<Q', self.read(a, 8))[0]
    def w8(self, a, v): self.write(a, bytes([v & 0xff]))
    def w32(self, a, v):
        assert a % 4 == 0, 'unaligned sw %08x' % a
        self.write(a, struct.pack('<I', v & 0xffffffff))
    def w64(self, a, v):
        assert a % 8 == 0, 'unaligned sd %08x' % a
        self.write(a, struct.pack('<Q', v & M64))

    def cstr(self, a, n=256):
        out = bytearray()
        while len(out) < n:
            c = self.u8(a + len(out))
            if c == 0:
                break
            out.append(c)
        return out.decode('latin1')


class CPU:
    RET_MAGIC = 0x0BAD0000

    def __init__(self, mem, code_lo, code_hi):
        self.m = mem
        self.r = [0] * 32
        self.f = [0] * 32          # raw bits
        self.cc = False
        self.code_lo, self.code_hi = code_lo, code_hi
        self.stubs = {}
        self.steps = 0
        self.f[31] = f2b(1.0)
        self.trace_calls = []

    def call(self, addr, args=(), fargs=(), sp=0x01F00000, max_steps=5_000_000):
        regs = ['a0', 'a1', 'a2', 'a3', 't0', 't1', 't2', 't3']
        for i, v in enumerate(args):
            self.r[4 + i] = sx32(v)
        for i, v in enumerate(fargs):
            self.f[12 + i] = f2b(v)
        self.r[29] = sp
        self.r[31] = self.RET_MAGIC
        saved = list(self.r)
        savedf = list(self.f)
        self.run(addr, max_steps)
        # callee-saved checks
        for i in list(range(16, 24)) + [28, 29, 30]:
            assert self.r[i] == saved[i], 'callee-saved %d clobbered' % i
        for i in range(20, 32):
            assert self.f[i] == savedf[i], 'callee-saved $f%d clobbered' % i
        return self.r[2]

    def run(self, pc, max_steps):
        npc = pc + 4
        start_steps = self.steps
        while True:
            if pc == self.RET_MAGIC:
                return
            if not (self.code_lo <= pc < self.code_hi):
                stub = self.stubs.get(pc)
                if stub is None:
                    raise RuntimeError('call into unstubbed game code %08x (ra=%08x)' % (pc, self.r[31]))
                self.trace_calls.append(pc)
                stub(self)
                # clobber caller-saved regs to catch reliance on them
                for i in (1, 3, 8, 9, 10, 11, 12, 13, 14, 15, 24, 25):
                    self.r[i] = 0xDEADBEEF_DEADBEEF
                pc = self.r[31] & 0xffffffff
                npc = pc + 4
                continue
            self.steps += 1
            if self.steps - start_steps > max_steps:
                raise RuntimeError('step limit')
            w = self.m.u32(pc)
            jump = self.exec(pc, w)
            if jump is not None:
                if jump is False and w >> 26 in (0x14, 0x15):
                    pc += 8  # BEQL/BNEL annul their delay slot when not taken.
                    continue
                # execute delay slot
                dw = self.m.u32(pc + 4)
                j2 = self.exec(pc + 4, dw)
                assert j2 is None, 'branch in delay slot at %08x' % (pc + 4)
                if jump is False:  # not taken
                    pc = pc + 8
                else:
                    pc = jump
            else:
                pc += 4

    def exec(self, pc, w):
        r = self.r
        op = w >> 26; rs = (w >> 21) & 31; rt = (w >> 16) & 31; rd = (w >> 11) & 31
        sa = (w >> 6) & 31; fn = w & 63; imm = w & 0xffff
        simm = imm - 0x10000 if imm & 0x8000 else imm
        m = self.m

        def setr(i, v):
            if i:
                r[i] = v & M64

        def br(cond):
            return (pc + 4 + (simm << 2)) & 0xffffffff if cond else False

        if w == 0:
            return None
        if op == 0:
            if fn == 0x21: setr(rd, sx32(r[rs] + r[rt]))
            elif fn == 0x23: setr(rd, sx32(r[rs] - r[rt]))
            elif fn == 0x24: setr(rd, r[rs] & r[rt])
            elif fn == 0x25: setr(rd, r[rs] | r[rt])
            elif fn == 0x26: setr(rd, r[rs] ^ r[rt])
            elif fn == 0x27: setr(rd, ~(r[rs] | r[rt]))
            elif fn == 0x2a: setr(rd, 1 if s64(r[rs]) < s64(r[rt]) else 0)
            elif fn == 0x2b: setr(rd, 1 if r[rs] < r[rt] else 0)
            elif fn == 0x2d: setr(rd, r[rs] + r[rt])
            elif fn == 0x2f: setr(rd, r[rs] - r[rt])
            elif fn == 0x0a:
                if r[rt] == 0: setr(rd, r[rs])
            elif fn == 0x0b:
                if r[rt] != 0: setr(rd, r[rs])
            elif fn == 0x00: setr(rd, sx32(r[rt] << sa))
            elif fn == 0x02: setr(rd, sx32((r[rt] & 0xffffffff) >> sa))
            elif fn == 0x03: setr(rd, sx32(s32(r[rt]) >> sa))
            elif fn == 0x3a: setr(rd, r[rt] >> sa)  # dsrl, used by the native hero filter
            elif fn == 0x08: return r[rs] & 0xffffffff
            elif fn == 0x09:
                t = r[rs] & 0xffffffff
                setr(rd, pc + 8)
                return t
            else:
                raise NotImplementedError('special fn %x at %08x' % (fn, pc))
            return None
        if op == 1:
            if rt == 0: return br(s64(r[rs]) < 0)
            if rt == 1: return br(s64(r[rs]) >= 0)
            raise NotImplementedError
        if op == 2:
            return ((pc + 4) & 0xf0000000) | ((w & 0x3ffffff) << 2)
        if op == 3:
            r[31] = pc + 8
            return ((pc + 4) & 0xf0000000) | ((w & 0x3ffffff) << 2)
        if op == 4: return br(r[rs] == r[rt])
        if op == 5: return br(r[rs] != r[rt])
        if op == 0x14: return br(r[rs] == r[rt])
        if op == 0x15: return br(r[rs] != r[rt])
        if op == 6: return br(s64(r[rs]) <= 0)
        if op == 7: return br(s64(r[rs]) > 0)
        if op == 0x09: setr(rt, sx32(r[rs] + simm)); return None
        if op == 0x19: setr(rt, r[rs] + simm); return None
        if op == 0x0a: setr(rt, 1 if s64(r[rs]) < simm else 0); return None
        if op == 0x0b: setr(rt, 1 if r[rs] < (simm & M64) else 0); return None
        if op == 0x0c: setr(rt, r[rs] & imm); return None
        if op == 0x0d: setr(rt, r[rs] | imm); return None
        if op == 0x0e: setr(rt, r[rs] ^ imm); return None
        if op == 0x0f: setr(rt, sx32(imm << 16)); return None
        addr = (r[rs] + simm) & 0xffffffff
        if op == 0x23: setr(rt, sx32(m.u32(addr))); return None
        if op == 0x2b: m.w32(addr, r[rt]); return None
        if op == 0x24: setr(rt, m.u8(addr)); return None
        if op in (0x21, 0x25):
            v = m.u8(addr) | (m.u8(addr + 1) << 8)
            setr(rt, v - 0x10000 if op == 0x21 and v & 0x8000 else v)
            return None
        if op == 0x20:
            v = m.u8(addr); setr(rt, v - 256 if v & 0x80 else v); return None
        if op == 0x28: m.w8(addr, r[rt]); return None
        if op == 0x29:
            m.w8(addr, r[rt]); m.w8(addr + 1, r[rt] >> 8); return None
        if op == 0x37: setr(rt, m.u64(addr)); return None
        if op == 0x3f: m.w64(addr, r[rt]); return None
        if op == 0x31: self.f[rt] = m.u32(addr); return None
        if op == 0x39: m.w32(addr, self.f[rt]); return None
        if op == 0x11:
            fmt = rs
            if fmt == 0x04: self.f[rd] = r[rt] & 0xffffffff; return None       # mtc1
            if fmt == 0x00: setr(rt, sx32(self.f[rd])); return None           # mfc1
            if fmt == 0x08:                                                    # bc1x
                tf = (w >> 16) & 1
                return br(self.cc == bool(tf))
            ft, fs, fd = rt, rd, sa
            if fmt == 0x14 and fn == 0x20:
                self.f[fd] = f2b(float(s32(self.f[fs]))); return None
            if fmt == 0x10:
                a, b = b2f(self.f[fs]), b2f(self.f[ft])
                if fn == 0x00: self.f[fd] = f2b(a + b)
                elif fn == 0x01: self.f[fd] = f2b(a - b)
                elif fn == 0x02: self.f[fd] = f2b(a * b)
                elif fn == 0x03: self.f[fd] = f2b(a / b)
                elif fn == 0x06: self.f[fd] = self.f[fs]
                elif fn == 0x07: self.f[fd] = f2b(-a)
                elif fn == 0x24: self.f[fd] = int(a) & 0xffffffff
                elif fn == 0x32: self.cc = a == b
                elif fn == 0x34: self.cc = a < b
                elif fn == 0x36: self.cc = a <= b
                else:
                    raise NotImplementedError('fpu fn %x at %08x' % (fn, pc))
                return None
        raise NotImplementedError('op %x at %08x (%08x)' % (op, pc, w))


def c_format(fmt, ints, mem):
    """Very small printf for %s %d %x %02d."""
    out = []
    it = iter(ints)
    def rep(mo):
        spec = mo.group(0)
        if spec == '%%':
            return '%'
        v = next(it)
        if spec.endswith('s'):
            return mem.cstr(v & 0xffffffff)
        if spec.endswith('d'):
            return (spec[:-1] + 'd') % s32(v)
        if spec.endswith('x'):
            return (spec[:-1] + 'x') % (v & 0xffffffff)
        return spec
    return re.sub(r'%%|%[-0-9.]*[sdx]', rep, fmt)
