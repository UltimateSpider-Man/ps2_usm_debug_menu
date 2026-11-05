"""Minimal two-pass assembler for the PS2 EE (R5900), little-endian.

Only the instruction subset needed by the injected debug menu is supported.
Safety checks performed at assembly time:
  * branch targets in range
  * R5900 short-loop erratum: backward branches must enclose >= 7 instructions
  * FPU compare -> bc1t/bc1f must be separated by >= 1 instruction
  * writes to $gp / $k0 / $k1 / $f31 are rejected (game relies on them)
"""
import struct

REGS = ['zero', 'at', 'v0', 'v1', 'a0', 'a1', 'a2', 'a3', 't0', 't1', 't2', 't3', 't4', 't5', 't6', 't7',
        's0', 's1', 's2', 's3', 's4', 's5', 's6', 's7', 't8', 't9', 'k0', 'k1', 'gp', 'sp', 'fp', 'ra']
R = {n: i for i, n in enumerate(REGS)}
R['s8'] = 30
FORBIDDEN_W = {R['gp'], R['k0'], R['k1']}


def reg(r):
    if isinstance(r, int):
        return r
    r = r.lstrip('$')
    return R[r]


def freg(f):
    if isinstance(f, int):
        return f
    f = f.lstrip('$')
    assert f[0] == 'f'
    return int(f[1:])


class Ref:
    """Deferred value: label (+ offset), hi/lo split."""
    def __init__(self, label, off=0, part=None):
        self.label, self.off, self.part = label, off, part

    def resolve(self, labels):
        if isinstance(self.label, int):
            v = self.label + self.off
        else:
            if self.label not in labels:
                raise KeyError('undefined label %s' % self.label)
            v = labels[self.label] + self.off
        v &= 0xffffffff
        if self.part == 'hi':
            return ((v + 0x8000) >> 16) & 0xffff
        if self.part == 'lo':
            return v & 0xffff
        return v


def _val(x, labels):
    if isinstance(x, Ref):
        return x.resolve(labels)
    if isinstance(x, str):
        return labels[x]
    return x


class Asm:
    def __init__(self, base):
        self.base = base
        self.items = []          # (addr, size, kind, payload)
        self.pc = base
        self.labels = {}
        self.meta = {}           # addr -> description for checks
        self.local_id = 0

    # ---------------- infrastructure -----------------
    def label(self, name):
        if name in self.labels:
            raise ValueError('duplicate label ' + name)
        self.labels[name] = self.pc

    def newlabel(self, prefix='L'):
        self.local_id += 1
        return '.%s%d' % (prefix, self.local_id)

    def _ins(self, fn, kind='ins', info=None):
        self.items.append((self.pc, 4, kind, fn, info))
        self.pc += 4

    def align(self, n):
        while self.pc % n:
            self.items.append((self.pc, 1, 'byte', 0, None))
            self.pc += 1

    def word(self, v):
        self.align(4)
        self.items.append((self.pc, 4, 'word', v, None))
        self.pc += 4

    def float32(self, f):
        self.word(struct.unpack('<I', struct.pack('<f', f))[0])

    def asciiz(self, s):
        b = s.encode('latin1') + b'\0'
        for c in b:
            self.items.append((self.pc, 1, 'byte', c, None))
            self.pc += 1

    def space(self, n):
        self.items.append((self.pc, n, 'space', n, None))
        self.pc += n

    # ---------------- encoders -----------------
    @staticmethod
    def _r(op, rs, rt, rd, sa, fn):
        return (op << 26) | (rs << 21) | (rt << 16) | (rd << 11) | (sa << 6) | fn

    @staticmethod
    def _i(op, rs, rt, imm):
        return (op << 26) | (rs << 21) | (rt << 16) | (imm & 0xffff)

    def _chkw(self, r):
        if r in FORBIDDEN_W:
            raise ValueError('write to reserved register %s at %x' % (REGS[r], self.pc))

    def _chkf(self, f):
        if f == 31:
            raise ValueError('write to $f31 (game constant 1.0) at %x' % self.pc)

    # R-type ALU
    def _alu(fn):
        def m(self, rd, rs, rt):
            rd, rs, rt = reg(rd), reg(rs), reg(rt)
            self._chkw(rd)
            self._ins(lambda L, a: Asm._r(0, rs, rt, rd, 0, fn), info=('w', rd))
        return m
    addu = _alu(0x21); subu = _alu(0x23); and_ = _alu(0x24); or_ = _alu(0x25); xor = _alu(0x26)
    nor = _alu(0x27); slt = _alu(0x2a); sltu = _alu(0x2b); daddu = _alu(0x2d); dsubu = _alu(0x2f)
    movz = _alu(0x0a); movn = _alu(0x0b)

    def _shift(fn):
        def m(self, rd, rt, sa):
            rd, rt = reg(rd), reg(rt)
            self._chkw(rd)
            self._ins(lambda L, a: Asm._r(0, 0, rt, rd, sa & 31, fn), info=('w', rd))
        return m
    sll = _shift(0x00); srl = _shift(0x02); sra = _shift(0x03)

    def _shiftv(fn):
        def m(self, rd, rt, rs):
            rd, rt, rs = reg(rd), reg(rt), reg(rs)
            self._chkw(rd)
            self._ins(lambda L, a: Asm._r(0, rs, rt, rd, 0, fn), info=('w', rd))
        return m
    sllv = _shiftv(0x04); srlv = _shiftv(0x06); srav = _shiftv(0x07)

    def mult(self, rd, rs, rt):          # R5900 3-operand mult (rd <- lo)
        rd, rs, rt = reg(rd), reg(rs), reg(rt)
        self._chkw(rd)
        self._ins(lambda L, a: Asm._r(0, rs, rt, rd, 0, 0x18), info=('w', rd))

    def mflo(self, rd):
        rd = reg(rd); self._chkw(rd)
        self._ins(lambda L, a: Asm._r(0, 0, 0, rd, 0, 0x12), info=('w', rd))

    def jr(self, rs):
        rs = reg(rs)
        self._ins(lambda L, a: Asm._r(0, rs, 0, 0, 0, 0x08), kind='jump')

    def jalr(self, rs, rd='ra'):
        rs, rd = reg(rs), reg(rd)
        self._ins(lambda L, a: Asm._r(0, rs, 0, rd, 0, 0x09), kind='jump')

    def nop(self):
        self._ins(lambda L, a: 0)

    # I-type
    def _imm(op, signed=True):
        def m(self, rt, rs, imm):
            rt, rs = reg(rt), reg(rs)
            self._chkw(rt)
            def enc(L, a, rt=rt, rs=rs, imm=imm):
                v = _val(imm, L)
                if signed and not isinstance(imm, Ref):
                    assert -0x8000 <= v <= 0x7fff, 'imm out of range %d at %x' % (v, a)
                if not signed and not isinstance(imm, Ref):
                    assert 0 <= v <= 0xffff, 'uimm out of range %d at %x' % (v, a)
                return Asm._i(op, rs, rt, v)
            self._ins(enc, info=('w', rt))
        return m
    addiu = _imm(0x09); daddiu = _imm(0x19); slti = _imm(0x0a); sltiu = _imm(0x0b)
    andi = _imm(0x0c, False); ori = _imm(0x0d, False); xori = _imm(0x0e, False)

    def lui(self, rt, imm):
        rt = reg(rt); self._chkw(rt)
        self._ins(lambda L, a: Asm._i(0x0f, 0, rt, _val(imm, L)), info=('w', rt))

    def _mem(op, is_load):
        def m(self, rt, off, base):
            rt, base = reg(rt), reg(base)
            if is_load:
                self._chkw(rt)
            def enc(L, a, rt=rt, base=base, off=off):
                v = _val(off, L)
                if not isinstance(off, Ref):
                    assert -0x8000 <= v <= 0x7fff, 'offset out of range at %x' % a
                return Asm._i(op, base, rt, v)
            self._ins(enc, info=('w', rt) if is_load else None)
        return m
    lb = _mem(0x20, True); lh = _mem(0x21, True); lw = _mem(0x23, True); lbu = _mem(0x24, True)
    lhu = _mem(0x25, True); ld = _mem(0x37, True); lq = _mem(0x1e, True)
    sb = _mem(0x28, False); sh = _mem(0x29, False); sw = _mem(0x2b, False); sd = _mem(0x3f, False)
    sq = _mem(0x1f, False)

    def lwc1(self, ft, off, base):
        ft, base = freg(ft), reg(base); self._chkf(ft)
        self._ins(lambda L, a: Asm._i(0x31, base, ft, _val(off, L)))

    def swc1(self, ft, off, base):
        ft, base = freg(ft), reg(base)
        self._ins(lambda L, a: Asm._i(0x39, base, ft, _val(off, L)))

    # branches
    def _br(self, op, rs, rt, target, kind='branch'):
        def enc(L, a):
            t = _val(target, L)
            d = (t - (a + 4))
            assert d % 4 == 0
            d >>= 2
            assert -0x8000 <= d <= 0x7fff, 'branch out of range at %x' % a
            return Asm._i(op, rs, rt, d)
        self._ins(enc, kind=kind, info=('target', target))

    def beq(self, rs, rt, t): self._br(4, reg(rs), reg(rt), t)
    def bne(self, rs, rt, t): self._br(5, reg(rs), reg(rt), t)
    def blez(self, rs, t): self._br(6, reg(rs), 0, t)
    def bgtz(self, rs, t): self._br(7, reg(rs), 0, t)
    def bltz(self, rs, t): self._br(1, reg(rs), 0, t)
    def bgez(self, rs, t): self._br(1, reg(rs), 1, t)
    def beqz(self, rs, t): self.beq(rs, 'zero', t)
    def bnez(self, rs, t): self.bne(rs, 'zero', t)
    def b(self, t): self.beq('zero', 'zero', t)

    def bc1t(self, t):
        self._br(0x11, 8, 1, t, kind='bc1')

    def bc1f(self, t):
        self._br(0x11, 8, 0, t, kind='bc1')

    def j(self, t):
        def enc(L, a):
            v = _val(t, L)
            assert (v & 0xf0000000) == ((a + 4) & 0xf0000000)
            return (2 << 26) | ((v >> 2) & 0x3ffffff)
        self._ins(enc, kind='jump')

    def jal(self, t):
        def enc(L, a):
            v = _val(t, L)
            assert (v & 0xf0000000) == ((a + 4) & 0xf0000000)
            return (3 << 26) | ((v >> 2) & 0x3ffffff)
        self._ins(enc, kind='jump')

    # COP1 (single precision)
    def mtc1(self, rt, fs):
        rt, fs = reg(rt), freg(fs); self._chkf(fs)
        self._ins(lambda L, a: Asm._r(0x11, 0x04, rt, fs, 0, 0))

    def mfc1(self, rt, fs):
        rt, fs = reg(rt), freg(fs); self._chkw(rt)
        self._ins(lambda L, a: Asm._r(0x11, 0x00, rt, fs, 0, 0), info=('w', rt))

    def _fop(fn, n=3):
        def m(self, fd, fs, ft=None):
            fd, fs = freg(fd), freg(fs)
            ft = freg(ft) if ft is not None else 0
            self._chkf(fd)
            self._ins(lambda L, a: (0x11 << 26) | (0x10 << 21) | (ft << 16) | (fs << 11) | (fd << 6) | fn)
        return m
    add_s = _fop(0x00); sub_s = _fop(0x01); mul_s = _fop(0x02); div_s = _fop(0x03)
    abs_s = _fop(0x05); mov_s = _fop(0x06); neg_s = _fop(0x07)

    def cvt_s_w(self, fd, fs):
        fd, fs = freg(fd), freg(fs); self._chkf(fd)
        self._ins(lambda L, a: (0x11 << 26) | (0x14 << 21) | (fs << 11) | (fd << 6) | 0x20)

    def cvt_w_s(self, fd, fs):
        fd, fs = freg(fd), freg(fs); self._chkf(fd)
        self._ins(lambda L, a: (0x11 << 26) | (0x10 << 21) | (fs << 11) | (fd << 6) | 0x24)

    def _fcmp(cond):
        def m(self, fs, ft):
            fs, ft = freg(fs), freg(ft)
            self._ins(lambda L, a: (0x11 << 26) | (0x10 << 21) | (ft << 16) | (fs << 11) | (0x30 | cond), kind='fcmp')
        return m
    # R5900 only implements C.F/C.EQ/C.LT/C.LE with funct 0x30/0x32/0x34/0x36
    # (what generic MIPS calls c.olt/c.ole); 0x3c/0x3e are NOT valid on the EE.
    c_eq_s = _fcmp(0x2); c_lt_s = _fcmp(0x4); c_le_s = _fcmp(0x6)

    # ---------------- pseudo ops -----------------
    def move(self, rd, rs):
        self.daddu(rd, rs, 'zero')

    def li(self, rt, v):
        v &= 0xffffffff
        sv = v - (1 << 32) if v & 0x80000000 else v
        if -0x8000 <= sv <= 0x7fff:
            self.addiu(rt, 'zero', sv)
        elif (v & 0xffff) == 0:
            self.lui(rt, v >> 16)
        else:
            self.lui(rt, v >> 16)
            self.ori(rt, rt, v & 0xffff)

    def la(self, rt, label, off=0):
        self.lui(rt, Ref(label, off, 'hi'))
        self.addiu(rt, rt, Ref(label, off, 'lo'))

    def lw_abs(self, rt, label, off=0, tmp=None):
        """rt = *(u32*)(label+off)"""
        t = tmp or rt
        self.lui(t, Ref(label, off, 'hi'))
        self.lw(rt, Ref(label, off, 'lo'), t)

    def sw_abs(self, rt, label, off=0, tmp='at'):
        self.lui(tmp, Ref(label, off, 'hi'))
        self.sw(rt, Ref(label, off, 'lo'), tmp)

    def li_f(self, fd, value, tmp='at'):
        bits = struct.unpack('<I', struct.pack('<f', value))[0]
        if bits == 0:
            self.mtc1('zero', fd)
        else:
            self.li(tmp, bits)
            self.mtc1(tmp, fd)

    # ---------------- function frame helper -----------------
    def func(self, name, saves=(), fsaves=(), locals_size=0):
        """Emit prologue. Returns an epilogue emitter; call .ret() to jump to it."""
        return Frame(self, name, list(saves), list(fsaves), locals_size)

    # ---------------- assembly -----------------
    def assemble(self):
        L = self.labels
        out = bytearray()
        addr_to_kind = {}
        words = {}
        for (a, size, kind, payload, info) in self.items:
            assert a - self.base == len(out), (hex(a), hex(self.base + len(out)))
            if kind in ('ins', 'jump', 'branch', 'bc1', 'fcmp'):
                w = payload(L, a)
                words[a] = (w, kind, info)
                out += struct.pack('<I', w & 0xffffffff)
            elif kind == 'word':
                out += struct.pack('<I', _val(payload, L) & 0xffffffff)
            elif kind == 'byte':
                out.append(payload)
            elif kind == 'space':
                out += b'\0' * payload
        self._checks(words)
        return bytes(out)

    def _checks(self, words):
        for a, (w, kind, info) in words.items():
            if kind == 'branch' or kind == 'bc1':
                t = _val(info[1], self.labels)
                if t <= a:
                    n = (a + 4 - t) // 4 + 1  # include delay slot
                    if n < 7:
                        raise ValueError('short loop (%d insns) ending at %x -> pad with nops' % (n, a))
            if kind == 'bc1':
                prev = words.get(a - 4)
                if prev and prev[1] == 'fcmp':
                    raise ValueError('bc1x immediately after c.cond.s at %x' % a)
            if kind in ('branch', 'bc1', 'jump'):
                nxt = words.get(a + 4)
                if nxt and nxt[1] in ('branch', 'bc1', 'jump'):
                    raise ValueError('branch in delay slot at %x' % (a + 4))
                # a lui in a delay slot means a li/la pseudo-op got split across the slot
                if nxt and (nxt[0] >> 26) == 0x0f:
                    raise ValueError('multi-instruction pseudo-op in delay slot at %x' % (a + 4))


class Frame:
    def __init__(self, A, name, saves, fsaves, locals_size):
        self.A = A
        self.name = name
        self.saves = saves
        self.fsaves = fsaves
        self.locals = (locals_size + 15) & ~15
        nreg = len(saves) + 1  # + ra
        self.reg_off = self.locals
        self.f_off = self.reg_off + 8 * nreg
        size = self.f_off + 4 * len(fsaves)
        self.size = (size + 15) & ~15
        self.epi = '.%s_epilogue' % name
        A.align(8)
        A.label(name)
        A.addiu('sp', 'sp', -self.size)
        for i, r in enumerate(saves):
            A.sd(r, self.reg_off + 8 * i, 'sp')
        A.sd('ra', self.reg_off + 8 * len(saves), 'sp')
        for i, f in enumerate(fsaves):
            A.swc1(f, self.f_off + 4 * i, 'sp')

    def ret(self):
        """Branch to epilogue (fills delay slot with nop)."""
        self.A.b(self.epi)
        self.A.nop()

    def end(self):
        A = self.A
        A.label(self.epi)
        for i, r in enumerate(self.saves):
            A.ld(r, self.reg_off + 8 * i, 'sp')
        A.ld('ra', self.reg_off + 8 * len(self.saves), 'sp')
        for i, f in enumerate(self.fsaves):
            A.lwc1(f, self.f_off + 4 * i, 'sp')
        A.jr('ra')
        A.addiu('sp', 'sp', self.size)
