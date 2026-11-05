"""Run the actual retail SLF routine and compare it with the reporting wrapper."""
from pathlib import Path
import struct
import dm_build as D
import dm_slf as X
from emu import Mem, CPU, f2b, b2f, c_format


def run():
    A, blob = D.build()
    mem = Mem(); mem.write(D.BASE, blob)
    mem.write(0x01000000, bytes(0x10000)); mem.write(0x01E00000, bytes(0x100000))
    # Copy this leaf routine verbatim into a free test-only code range. Its
    # internal branches are PC-relative and its sole external JAL is unchanged.
    native = 0x000FF000
    clean = (Path(__file__).resolve().parents[1] / 'source/SLES_536.72').read_bytes()
    body = clean[X.NATIVE_CALL - 0x100000 + 0x1000:0x2F7740 - 0x100000 + 0x1000]
    assert len(body) == 0xD4 and int.from_bytes(body[:4], 'little') == 0x27BDFFD0
    mem.write(native, body)
    replacements = 0
    for pc in range(A.labels['hook_slf_call'], A.labels['dm_slf_code_end'], 4):
        word = mem.u32(pc)
        if word >> 26 in (2, 3) and (word & 0x3FFFFFF) << 2 == X.NATIVE_CALL:
            mem.w32(pc, (word & 0xFC000000) | (native >> 2)); replacements += 1
    assert replacements == 2
    mem.w32(0x6F6C24, f2b(10.0))  # Real native threshold operand.
    cpu = CPU(mem, D.BASE, 0x100000)
    thread, arg, function, vtable = 0x01000000, 0x01000400, 0x01000500, 0x01000600
    old_pc, callback = 0x01002000, 0x007D0200
    mem.w32(arg, function); mem.w32(function, vtable)
    mem.write(vtable + 0x10, struct.pack('<h', 4)); mem.w32(vtable + 0x14, callback)
    state = dict(done=False, dt=1.0)
    reports = []
    callback_entries = []

    def slf(c):
        assert c.r[4] == function + 4 and c.r[5] == thread + 0x20
        callback_entries.append(c.r[6])
        mem.w32(thread + 0x1A4, 0x11223344)  # Native recall restores the old SP.
        c.r[2] = int(state['done'])
    def time_inc(c): c.f[0] = f2b(state['dt'])
    def output(c):
        reports.append(c_format(mem.cstr(c.r[4]), c.r[5:12], mem))
        c.r[2] = 0xFFFFFFFF  # Logger return must not replace the native result.
    cpu.stubs.update({callback: slf, X.GET_TIME_INC: time_inc, X.KPRINTF: output})

    def reset(timer, previous, entry=0):
        mem.write(thread, bytes(0x300))
        mem.w32(thread + 0x1A4, 0x12345678)
        mem.w32(thread + X.THREAD_LAST_PC, previous)
        mem.w32(thread + X.THREAD_TIMER, f2b(timer))
        mem.w32(thread + 0x1D8, entry)
        reports.clear(); callback_entries.clear()

    def outcome(address):
        result = cpu.call(address, args=(thread, arg, old_pc))
        fields = tuple(mem.u32(thread + off) for off in (0x1A4, 0x1AC, 0x1B0, 0x1B4, 0x1D8))
        return result, fields, list(callback_entries)

    cases = [
        # enabled, completed, prior timer, timestep, prior instruction, reports
        (False, False, 9.5, 1.0, old_pc, 0),
        (True, False, 9.5, 1.0, old_pc, 1),
        (True, False, 9.0, 1.0, old_pc, 0),  # Exactly ten is not a timeout.
        (True, False, 0.0, 10.5, old_pc, 1),
        (True, False, 9.5, 1.0, old_pc + 2, 0),
        (True, True, 9.5, 1.0, old_pc, 0),
        (True, False, 3.0, 0.0, old_pc, 0),
    ]
    for enabled, done, timer, dt, previous, count in cases:
        state.update(done=done, dt=dt)
        reset(timer, previous); expected = outcome(native)
        reset(timer, previous)
        mem.w32(A.labels['dm_report_slf_recall_timeouts'], enabled)
        before = mem.u32(A.labels['dm_slf_report_count'])
        actual = outcome(A.labels['hook_slf_call'])
        assert actual == expected, (enabled, done, timer, dt, actual, expected)
        assert len(reports) == count
        assert mem.u32(A.labels['dm_slf_report_count']) == before + count
        if count:
            assert reports == ['SLF recall timeout: thread=0x01000000 PC=0x01002000 (over 10 seconds)\n']

    # Reset/repeated recalls report once per native interval, not every frame.
    state.update(done=False, dt=1.0); reset(9.5, old_pc)
    mem.w32(A.labels['dm_report_slf_recall_timeouts'], 1)
    outcome(A.labels['hook_slf_call'])
    assert len(reports) == 1 and mem.u32(thread + X.THREAD_TIMER) == f2b(0.0)
    outcome(A.labels['hook_slf_call'])
    assert len(reports) == 1 and b2f(mem.u32(thread + X.THREAD_TIMER)) == 1.0
    print('SLF reporting/native equivalence and ten-second boundary checks passed:', cpu.steps, 'steps')


if __name__ == '__main__': run()
