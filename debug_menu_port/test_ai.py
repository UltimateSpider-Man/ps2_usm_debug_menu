"""Executable R5900 scenarios for the live AI browser and native host export.

Run directly with python debug_menu_port/test_ai.py. Native I/O is stubbed;
the actual injected navigation, formatting, pointer guards and export run.
"""
import struct
import dm_build as D
import dm_ai as AI
from emu import Mem, CPU, f2b, b2f, c_format, s32


def run():
    modules = D.EXTRA_MODULES
    if AI not in modules:
        D.EXTRA_MODULES = (*modules, AI)
        # Compatibility with the pre-integration tree's replaced static menu.
        if 'dm_ai_menu' in D.dm_game_extra.MENUS:
            D.dm_game_extra.MENUS = tuple(x for x in D.dm_game_extra.MENUS if x != 'dm_ai_menu')
    A, blob = D.build()
    mem = Mem(); mem.write(D.BASE, blob)
    mem.write(0x01000000, bytes(0x200000)); mem.write(0x01E00000, bytes(0x100000))
    cpu = CPU(mem, D.BASE, A.labels['dm_end'])
    def call(name, *args): return cpu.call(A.labels[name], args=args)
    def addr(name): return A.labels[name]
    def var(name): return mem.u32(addr(name))
    def writevar(name, value): mem.w32(addr(name), value)
    def text(pointer, value): mem.write(pointer, value.encode() + b'\0')
    def entries(menu):
        out = {}; p = mem.u32(addr(menu) + D.M_FIRST)
        while p:
            name = mem.cstr(mem.u32(p + D.E_NAME)); assert name not in out, name
            out[name] = p; p = mem.u32(p + D.E_NEXT)
        assert len(out) == mem.u32(addr(menu) + D.M_COUNT)
        return out
    def value(entry):
        call('dm_value_text', entry, 0x011F1000)
        return mem.cstr(0x011F1000)
    def snprintf(c):
        fmt = mem.cstr(c.r[6] & 0xFFFFFFFF)
        rendered = c_format(fmt, c.r[7:12], mem)
        n = c.r[5] & 0xFFFFFFFF
        # Match real snprintf truncation (long fixed strings can be clipped).
        mem.write(c.r[4] & 0xFFFFFFFF, rendered.encode()[:n - 1] + b'\0')
        c.r[2] = len(rendered)
    cpu.stubs[D.G['snprintf']] = snprintf
    def compare(c):
        a, b = (mem.cstr(c.r[i] & 0xFFFFFFFF).lower() for i in (4, 5))
        c.r[2] = ((a > b) - (a < b)) & 0xFFFFFFFFFFFFFFFF
    cpu.stubs[D.G['strcasecmp']] = compare
    cpu.stubs[D.G['enable_physics']] = lambda c: None
    files, closed = [], []
    io = {'fail_open': False, 'fail_write': False, 'fail_close': False}
    def open_file(c):
        assert c.r[5] == 0x602
        name = mem.cstr(c.r[4] & 0xFFFFFFFF)
        assert name == 'host:param_dump_0x00001000.txt', name
        if io['fail_open']: c.r[2] = -1
        else:
            files.append(bytearray()); c.r[2] = 7
    def write_file(c):
        assert c.r[4] == 7
        if io['fail_write']: c.r[2] = -1; return
        count = min(c.r[6], 17)  # Deliberately exercise partial writes.
        files[-1].extend(mem.read(c.r[5] & 0xFFFFFFFF, count)); c.r[2] = count
    def close_file(c):
        closed.append(c.r[4]); c.r[2] = -1 if io['fail_close'] else 0
    cpu.stubs[AI.SCE_OPEN] = open_file
    cpu.stubs[AI.SCE_WRITE] = write_file
    cpu.stubs[AI.SCE_CLOSE] = close_file

    LIST, SENTINEL, NODES, CORES, OWNERS = 0x01000000, 0x01000100, 0x01000200, 0x01010000, 0x01020000
    mem.w32(AI.AI_LIST, LIST); mem.w32(LIST + 4, SENTINEL); mem.w32(SENTINEL, NODES)
    for i in range(65):
        node, core, owner = NODES + i * 16, CORES + i * 0x100, OWNERS + i * 0x100
        mem.w32(node, node + 16 if i < 64 else SENTINEL); mem.w32(node + 8, core)
        mem.w32(core + 0x58, owner); mem.w32(owner + 0x10, 0x1000 + i)
        mem.w32(owner + D.ENTITY_HANDLE, 0x5000 + i)
    # Flagged actor is absent from the browser, not merely disabled.
    mem.w32(OWNERS + 64 * 0x100 + 4, 0x800)
    ROOT_ENTRY = 0x01100000; text(0x01100100, 'AI'); mem.w32(ROOT_ENTRY, 0x01100100)
    call('p_ai', ROOT_ENTRY)
    root = entries('dm_ai_menu'); assert len(root) == 33
    assert '0x00001000' in root and '--More--' in root
    call('h_ai_root_next'); root2 = entries('dm_ai_menu')
    assert len(root2) == 33 and '0x0000103f' in root2 and '0x00001040' not in root2
    call('h_ai_root_prev'); root = entries('dm_ai_menu')

    IVEC, IPTRS, INODES = 0x01040000, 0x01041000, 0x01042000
    mem.w32(CORES + 0x54, IVEC); mem.w32(IVEC + 4, 34); mem.w32(IVEC + 8, IPTRS)
    for i in range(34):
        inode = INODES + i * 0x40
        mem.w32(IPTRS + i * 4, inode); mem.w32(inode + 4, 0x2000 + i)
    call('p_ai_actor', root['0x00001000']); actor = entries('dm_ai_actor_menu')
    assert len(actor) == 34 and '-Core params' in actor
    call('h_ai_actor_next'); actor2 = entries('dm_ai_actor_menu')
    assert len(actor2) == 4 and '0x00002021 inode params' in actor2
    call('h_ai_actor_prev'); actor = entries('dm_ai_actor_menu')
    assert entries('dm_ai_menu') == root  # Child pools retain parent links/names.
    call('p_ai_params', actor['0x00002000 inode params'])
    assert list(entries('dm_ai_params_menu')) == ['--None defined--']
    assert mem.u32(addr('dm_ai_params_menu') + D.M_PARENT) == addr('dm_ai_actor_menu')
    assert entries('dm_ai_actor_menu') == actor

    ARRAY, PTRS, PARAMS = 0x01050000, 0x01051000, 0x01052000
    mem.w32(CORES + 0x48, ARRAY); mem.w32(ARRAY + 4, 35); mem.w32(ARRAY + 8, PTRS)
    for i in range(35):
        p = PARAMS + i * 16
        mem.w32(PTRS + 4 * i, p); mem.w32(p + 8, 0x3000 + i)
        typ = i if i < 6 else 0
        mem.w32(p + 4, typ); mem.w32(p, f2b(i + .25) if not typ else i)
    mem.w32(PARAMS + 16, 0xFFFFFFFC)  # signed integer -4
    text(0x01060000, 'test string'); mem.w32(PARAMS + 48, 0x01060000)
    mem.w32(PARAMS + 64, 0x01060100); mem.write(0x01060100, struct.pack('<3f', -1, 2.5, 3.75))
    mem.w32(PARAMS + 80, 0x01060200); mem.write(0x01060200, struct.pack('<3f', 2.5, .25, 0))
    call('p_ai_params', actor['-Core params']); params = entries('dm_ai_params_menu')
    assert len(params) == 34
    assert value(params['0x00003000']) == '0.25'
    call('dm_on_change', params['0x00003000'], 1)
    assert abs(b2f(mem.u32(PARAMS)) - .55) < .00001
    call('dm_on_change', params['0x00003001'], -1); assert s32(mem.u32(PARAMS + 16)) == -5
    assert value(params['0x00003002']) == '0x00000002 (hash)'
    assert value(params['0x00003003']) == 'test string (fixedstring)'
    assert value(params['0x00003004']) == '(-1.00 2.50 3.75) (vector3d)'
    assert value(params['0x00003005']) == '(b2.50 v0.25) (float variance)'
    for i in range(2, 6):
        before = mem.read(PARAMS + 16 * i, 16)
        call('dm_on_change', params['0x%08x' % (0x3000 + i)], 1)
        assert mem.read(PARAMS + 16 * i, 16) == before
    call('h_ai_params_next'); last = entries('dm_ai_params_menu')
    assert len(last) == 5 and '0x00003022' in last
    assert entries('dm_ai_menu') == root and entries('dm_ai_actor_menu') == actor

    # Export all 35 records even from page two, and close on failure.
    call('h_ai_export', last['--Export this block--'])
    assert var('dm_ai_export_status') == 1 and len(closed) == 1
    dump = bytes(files[-1]).decode(); assert len(dump.splitlines()) == 36
    assert 'float 0x00003000 0.55' in dump and 'float 0x00003022 34.25' in dump
    io['fail_open'] = True; call('h_ai_export', last['--Export this block--'])
    assert s32(var('dm_ai_export_status')) == -1 and len(closed) == 1
    assert mem.cstr(mem.u32(last['--Export this block--'])) == 'Export failed (check host:)'
    io['fail_open'] = False; io['fail_write'] = True
    call('h_ai_export', last['--Export this block--']); assert len(closed) == 2
    io['fail_write'] = False; io['fail_close'] = True
    call('h_ai_export', last['--Export this block--']); assert len(closed) == 3 and s32(var('dm_ai_export_status')) == -1
    io['fail_close'] = False

    call('h_ai_params_prev'); params = entries('dm_ai_params_menu')
    def guard_closes():
        writevar('dm_active_menu', addr('dm_ai_params_menu')); call('dm_ai_validate')
        assert var('dm_active_menu') == 0
    writevar('dm_active_menu', addr('dm_ai_params_menu')); call('dm_ai_validate')
    assert var('dm_active_menu') == addr('dm_ai_params_menu')
    # Removal, allocator reuse, changed vector/slot/type and NaN stop editing.
    mem.w32(SENTINEL, SENTINEL); guard_closes(); mem.w32(SENTINEL, NODES)
    mem.w32(OWNERS + D.ENTITY_HANDLE, 9); guard_closes(); mem.w32(OWNERS + D.ENTITY_HANDLE, 0x5000)
    mem.w32(ARRAY + 8, PTRS + 4); guard_closes(); mem.w32(ARRAY + 8, PTRS)
    mem.w32(PTRS, PARAMS + 16); guard_closes(); mem.w32(PTRS, PARAMS)
    mem.w32(PARAMS + 4, 1); guard_closes(); mem.w32(PARAMS + 4, 0)
    mem.w32(PARAMS, 0x7FC00000); guard_closes(); mem.w32(PARAMS, f2b(.55))
    call('p_ai_params', actor['0x00002000 inode params'])
    mem.w32(IPTRS, INODES + 0x40); guard_closes(); mem.w32(IPTRS, INODES)
    # Replaced list cannot trigger stale native calls or parameter writes.
    mem.w32(AI.AI_LIST, 0x01FFFFFC); call('p_ai', ROOT_ENTRY)
    assert list(entries('dm_ai_menu')) == ['--None defined--']
    print('AI TESTS PASSED; steps:', cpu.steps, 'blob:', hex(len(blob)))


if __name__ == '__main__':
    run()
