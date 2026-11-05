"""Independent allocator-list fixtures for the read-only Memory menu."""
import dm_build as D
import dm_memory as X
from emu import Mem, CPU, c_format


def run():
    A, blob = D.build(); mem = Mem(); mem.write(D.BASE, blob)
    mem.write(0x1000000, bytes(0x10000)); mem.write(0x1E00000, bytes(0x100000))
    cpu = CPU(mem, D.BASE, A.labels['dm_end'])
    def call(name, *args): return cpu.call(A.labels[name], args=args)
    def fmt(c):
        text = c_format(mem.cstr(c.r[6]), c.r[7:12], mem).encode()
        mem.write(c.r[4], text[:c.r[5] - 1] + b'\0'); c.r[2] = len(text)
    cpu.stubs[D.G['snprintf']] = fmt
    partial, full, free, slabs = 0x1000000, 0x1001000, 0x1002000, 0x1003000
    for address, value in ((X.PARTIAL, partial), (X.FULL, full), (X.FREE, free), (X.INITIALIZED, 1)):
        mem.w32(address, value)
    def slab(addr, owner, size, allocated, next_node=0):
        mem.w32(addr, 0xE1E1E1E1); mem.w32(addr + 0x20, 0x1E1E1E1E)
        mem.write(addr + 0xA, size.to_bytes(2, 'little'))
        mem.write(addr + 0xC, (1920 // size if size else 0).to_bytes(2, 'little'))
        mem.write(addr + 0xE, allocated.to_bytes(2, 'little'))
        mem.w32(addr + 0x1C, owner); mem.w32(addr + 0x14, next_node)
    def header(addr, first, last, count):
        for off, value in ((0, first), (4, last), (8, count)): mem.w32(addr + off, value)
    # Two 8-byte partial slabs (2+7 objects), one full12-byte slab (160), two free slabs.
    header(partial + 12, slabs, slabs + 0x40, 2)
    slab(slabs, partial + 12, 8, 2, slabs + 0x40)
    slab(slabs + 0x40, partial + 12, 8, 7)
    header(full + 24, slabs + 0x80, slabs + 0x80, 1)
    slab(slabs + 0x80, full + 24, 12, 160)
    header(free, slabs + 0xC0, slabs + 0x100, 2)
    slab(slabs + 0xC0, free, 0, 0, slabs + 0x100); slab(slabs + 0x100, free, 0, 0)
    native_before = mem.read(partial, 0x4000)
    call('dm_slab_snapshot')
    values = A.labels['dm_slab_values']
    assert mem.u32(values) == 5 and mem.u32(values + 4) == 2
    def value(category, index): return mem.u32(values + 8 + (44 * category + index) * 4)
    assert value(0, 2) == 1 and value(1, 1) == 2
    assert value(2, 1) == 9 and value(2, 2) == 160
    assert value(3, 1) == 471 and value(3, 2) == 0
    assert mem.read(partial, 0x4000) == native_before
    # Entry population preserves a static parent and left/right never mutates its value.
    entry, out = 0x1008000, 0x1008100
    mem.w32(entry + D.E_NAME, out); mem.write(out, b'Allocated Objects\0')
    mem.w32(entry + D.E_ID, 2)
    call('p_slab_class', entry)
    menu = A.labels['dm_slab_classes']; first = mem.u32(menu + D.M_FIRST)
    assert mem.u32(menu + D.M_COUNT) == 44
    second = mem.u32(first + D.E_NEXT)
    call('dm_value_text', second, out + 64)
    assert mem.cstr(out + 64) == '9'
    call('dm_on_change', second, 1)
    assert mem.u32(second + D.E_VALUE) == 9
    assert mem.read(partial, 0x4000) == native_before
    # Counts are refreshed from allocator state on reentry.
    mem.write(slabs + 0xE, (3).to_bytes(2, 'little')); call('dm_slab_snapshot')
    assert value(2, 1) == 10 and value(3, 1) == 470
    # Corrupt count, cycle, owner and range must not hang or dereference outside EE RAM.
    for target, invalid in ((partial + 20, 99), (slabs + 0x14, slabs),
                            (slabs + 0x1C, 0), (partial + 12, 0x2000000),
                            (partial + 12, slabs + 1)):
        old = mem.u32(target); mem.w32(target, invalid); call('dm_slab_snapshot')
        assert mem.u32(values) == 0xFFFFFFFF
        mem.w32(target, old)
    mem.w32(X.INITIALIZED, 0); call('dm_slab_snapshot')
    assert mem.u32(values) == 0
    print('Memory slab snapshots/read-only/corruption checks passed:', cpu.steps, 'steps')


if __name__ == '__main__': run()
