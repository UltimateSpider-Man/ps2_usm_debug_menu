"""Private PS2 beta system font, used only by the injected menu.

The source is the user's local SLUS_208.70: TIM2 at 0x762380 (0x8500
bytes), FDF at 0x761300 (4177 bytes). Retail's global system font is never
replaced. The native TIM2 loader keeps its input alive, so the decoded
allocation deliberately lasts for the game session.
"""
from pathlib import Path
import hashlib
from asm5900 import Ref

MENUS = ()
DYNAMIC_MENUS = ()
TEXTURE_SIZE = 0x8500
FDF_SIZE = 4177
DECODED_SIZE = TEXTURE_SIZE + FDF_SIZE
TEXTURE_SHA256 = '0fb9e77bc167d16106011fa46f54c51ac7ef5e258abd50209fa1db2adf0669d2'
FDF_SHA256 = '9077050a1f7274f9f66b137b304b0a117ad00951bf1799594cbb2f0097240655'
MEM_ALLOC = 0x55B324
CONSTRUCT_TEXTURE = 0x579318
PARSE_FONT = 0x5928E0
NAME = 'dm_beta_menu_font'
ASSET = Path(__file__).with_name('beta_menu_font.lz')
# Runtime diagnostics: last reached operation, retained for a read-only PINE
# inspection. A failed initialization keeps its stage and native return value.
STAGE_ALLOCATE, STAGE_DECODE, STAGE_LOAD, STAGE_DIMENSIONS, STAGE_CREATE, STAGE_READY = range(1, 7)


def pack(data):
    """Literal tag 0..127: n+1 bytes; match tag 128..255: n+3, u16 distance."""
    out, literals, index = bytearray(), bytearray(), {}
    pos = 0

    def flush():
        if literals:
            out.append(len(literals) - 1)
            out.extend(literals)
            literals.clear()

    while pos < len(data):
        key = data[pos:pos + 3]
        best, distance = 0, 0
        for old in reversed(index.get(key, [])[-64:]):
            if pos - old > 65535:
                continue
            n = 0
            while n < 130 and pos + n < len(data) and data[old + n] == data[pos + n]:
                n += 1
            if n > best:
                best, distance = n, pos - old
        if best >= 4:
            flush()
            out.extend((0x80 | (best - 3), distance & 255, distance >> 8))
            used = best
        else:
            literals.append(data[pos])
            if len(literals) == 128:
                flush()
            used = 1
        for at in range(pos, pos + used):
            candidates = index.setdefault(data[at:at + 3], [])
            candidates.append(at)
            if len(candidates) > 64:
                del candidates[0]
        pos += used
    flush()
    return bytes(out)


def unpack(data):
    out, pos = bytearray(), 0
    while pos < len(data):
        tag = data[pos]
        pos += 1
        if tag & 0x80:
            if pos + 2 > len(data):
                raise ValueError('truncated font match')
            distance = int.from_bytes(data[pos:pos + 2], 'little')
            pos += 2
            if not 0 < distance <= len(out):
                raise ValueError('invalid font match')
            for _ in range((tag & 127) + 3):
                out.append(out[-distance])
        else:
            size = tag + 1
            if pos + size > len(data):
                raise ValueError('truncated font literal')
            out.extend(data[pos:pos + size])
            pos += size
    return bytes(out)


def asset():
    packed = ASSET.read_bytes()
    raw = unpack(packed)
    if (len(raw) != DECODED_SIZE or
            hashlib.sha256(raw[:TEXTURE_SIZE]).hexdigest() != TEXTURE_SHA256 or
            hashlib.sha256(raw[TEXTURE_SIZE:]).hexdigest() != FDF_SHA256):
        raise ValueError('beta menu font asset is not the verified PS2 font')
    return packed


def emit_code(A, S, C):
    def call(addr):
        A.jal(addr); A.nop()

    def stage(value):
        A.li('t0', value); A.sw_abs('t0', 'dm_font_stage')

    # a0=packed, a1=destination, a2=decoded size. All input is build-verified.
    f = A.func('dm_font_unpack')
    A.addu('t5', 'a1', 'a2')
    A.label('.font_token')
    A.beq('a1', 't5', f.epi); A.nop()
    A.lbu('t0', 0, 'a0'); A.addiu('a0', 'a0', 1)
    A.andi('t1', 't0', 127); A.andi('t0', 't0', 128)
    A.bnez('t0', '.font_match'); A.addiu('t1', 't1', 1)
    A.label('.font_literal')
    A.lbu('t2', 0, 'a0'); A.addiu('a0', 'a0', 1)
    A.sb('t2', 0, 'a1'); A.addiu('a1', 'a1', 1)
    A.addiu('t1', 't1', -1); A.bnez('t1', '.font_literal'); A.nop()
    A.b('.font_token'); A.nop()
    A.label('.font_match')
    A.lbu('t2', 0, 'a0'); A.lbu('t3', 1, 'a0')
    A.sll('t3', 't3', 8); A.or_('t2', 't2', 't3')
    A.subu('t3', 'a1', 't2'); A.addiu('a0', 'a0', 2)
    A.addiu('t1', 't1', 2)
    A.label('.font_copy')
    A.lbu('t2', 0, 't3'); A.addiu('t3', 't3', 1)
    A.sb('t2', 0, 'a1'); A.addiu('a1', 'a1', 1)
    A.addiu('t1', 't1', -1); A.bnez('t1', '.font_copy'); A.nop()
    A.b('.font_token'); A.nop()
    f.end()

    # Call from render after the native font exists; v0 is private or fallback.
    f = A.func('dm_font_init', saves=['s0', 's1', 's2'])
    A.lw_abs('v0', 'dm_menu_font')
    A.bnez('v0', f.epi); A.nop()
    A.lw_abs('s1', C['G']['nglSysFont'])
    A.beqz('s1', f.epi); A.move('v0', 's1')
    A.lw_abs('t0', 'dm_font_attempted')
    A.bnez('t0', f.epi); A.nop()
    A.li('t0', 1); A.sw_abs('t0', 'dm_font_attempted')
    stage(STAGE_ALLOCATE)
    A.li('a0', DECODED_SIZE); A.li('a1', 128); A.li('a2', 0x1000000)
    call(MEM_ALLOC)
    A.beqz('v0', '.font_failed'); A.move('s0', 'v0')
    A.sw_abs('s0', 'dm_font_storage')
    stage(STAGE_DECODE)
    A.la('a0', 'dm_font_packed'); A.move('a1', 's0'); A.li('a2', DECODED_SIZE)
    call('dm_font_unpack')
    stage(STAGE_LOAD)
    A.la('a0', 'dm_font_name'); A.move('a1', 'zero')
    A.move('a2', 's0'); A.li('a3', TEXTURE_SIZE)
    # During gameplay the texture directory returns nglDefaultTex on a miss.
    # The normal in-place loader treats it as an existing resource and never
    # constructs our texture. Construct directly; this texture is private.
    call(CONSTRUCT_TEXTURE)
    A.sw_abs('v0', 'dm_font_texture')
    stage(STAGE_DIMENSIONS)
    A.beqz('v0', '.font_failed'); A.nop()
    # Native loader returns a fallback texture on failure: check dimensions.
    A.lhu('t0', 0x56, 'v0'); A.li('t1', 256)
    A.bne('t0', 't1', '.font_failed'); A.nop()
    A.lhu('t0', 0x58, 'v0'); A.li('t1', 128)
    A.bne('t0', 't1', '.font_failed'); A.nop()
    # Match native system-font lifetime flag, on our private texture only.
    A.ld('t0', 0x68, 'v0'); A.ori('t0', 't0', 2); A.sd('t0', 0x68, 'v0')
    stage(STAGE_CREATE)
    # Mirror create_and_parse_fdf's 0x58-byte object initialization, but attach
    # the private texture instead of doing a second directory lookup by name.
    A.li('a0', 0x58); A.li('a1', 8); A.li('a2', 0x1000000)
    call(MEM_ALLOC)
    A.beqz('v0', '.font_failed'); A.nop()
    A.move('s2', 'v0')
    for offset in range(0, 0x58, 8):
        A.sd('zero', offset, 's2')
    A.la('t0', 'dm_font_name')
    for offset in range(0, 32, 4):
        A.lw('t1', offset, 't0'); A.sw('t1', offset, 's2')
    A.li('t0', 1); A.sw('t0', 0x20, 's2')
    A.li('t0', 2); A.sw('t0', 0x40, 's2'); A.sw('t0', 0x44, 's2')
    A.lw_abs('t0', 'dm_font_texture'); A.sw('t0', 0x24, 's2')
    A.li('t0', TEXTURE_SIZE); A.addu('a0', 's0', 't0'); A.move('a1', 's2')
    call(PARSE_FONT)
    A.li('t0', 1); A.sw('t0', 0x50, 's2')
    A.sw_abs('s2', 'dm_menu_font'); A.move('v0', 's2')
    stage(STAGE_READY)
    f.ret()
    A.label('.font_failed'); A.move('v0', 's1')
    f.end()

    f = A.func('dm_font_get')
    A.lw_abs('v0', 'dm_menu_font')
    A.bnez('v0', f.epi); A.nop()
    A.lw_abs('v0', C['G']['nglSysFont'])
    f.end()


def emit_menus(A, S, C):
    pass


def emit_data(A, S, C):
    A.align(4); A.label('dm_font_name')
    value = 0
    for c in NAME.lower().encode('ascii'):
        value = (value * 33 + c) & 0xffffffff
    A.word(value)
    A.asciiz(NAME)
    A.space(28 - len(NAME) - 1)
    A.label('dm_font_packed')
    for byte in asset():
        A.items.append((A.pc, 1, 'byte', byte, None)); A.pc += 1


def emit_bss(A, C):
    A.align(4)
    for name in ('dm_menu_font', 'dm_font_attempted', 'dm_font_storage',
                 'dm_font_stage', 'dm_font_texture'):
        A.label(name); A.word(0)
