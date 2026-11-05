"""Exercise discovery, owner binding, and unloading of real script actions."""
import struct
import dm_script_commands as M


def run(ctx):
    mem, cpu, D, A = (ctx[k] for k in ('mem', 'cpu', 'D', 'A'))
    tap, goto, var = (ctx[k] for k in ('tap', 'goto', 'var'))
    title = ctx['menu_title']
    mem.write(0x01300000, bytes(0x20000))
    MAP, HEAD, NODE, EXE = 0x01300000, 0x01300100, 0x01300200, 0x01300300
    OBJECT, INSTANCES, INSTANCE = 0x01300400, 0x01300500, 0x01300600
    FUNCTIONS, STRINGS, OBJECTS = 0x01300700, 0x01300800, 0x01300900
    MISSION_OBJECT, MISSION_INSTANCES, MISSION_INSTANCE = 0x01300A00, 0x01300B00, 0x01300C00
    mem.w32(M.EXEC_MAP, MAP); mem.w32(MAP + 4, HEAD)
    mem.w32(HEAD + 8, NODE); mem.w32(NODE + 0x20, EXE)
    mem.w32(EXE + 0x28, OBJECTS); mem.w32(EXE + 0x30, 2)
    mem.w32(OBJECTS, OBJECT); mem.w32(OBJECT + 0x20, FUNCTIONS)
    mem.w32(OBJECT, 0x2958857E)
    # The supplied earlier patched CITY resource redirected Game Finished to
    # an odd byte offset. The guarded disc repair restores its original
    # 13-word wrapper already present at byte offset 0x6BFA.
    finished = bytes.fromhex('011dc0410000090501003f000905010040000421fcff041e0400')
    FINISH_FN, FINISH_CODE = 0x01303000, 0x01303100
    mem.w32(FINISH_FN, OBJECT); mem.w32(FINISH_FN + 4, 0xF4B072A0)
    mem.w32(FINISH_FN + 12, 4); mem.w32(FINISH_FN + 0x10, FINISH_CODE)
    mem.w32(FINISH_FN + 0x14, 13); mem.w32(FINISH_FN + 0x1C, 2)
    mem.write(FINISH_CODE, finished)
    assert cpu.call(A.labels['dm_script_action_safe'], (FINISH_FN,)) == 1
    mem.w32(OBJECT + 0x2C, INSTANCES); mem.w32(INSTANCES, INSTANCE)
    mem.w32(INSTANCE + 0x2C, OBJECT)
    mem.w32(OBJECTS + 4, MISSION_OBJECT); mem.w32(MISSION_OBJECT, 0x95BCE7F8)
    mem.w32(MISSION_OBJECT + 0x20, FUNCTIONS + 12)
    mem.w32(MISSION_OBJECT + 0x2C, MISSION_INSTANCES)
    mem.w32(MISSION_INSTANCES, MISSION_INSTANCE)
    mem.w32(MISSION_INSTANCE + 0x2C, MISSION_OBJECT)
    mem.w32(EXE + 0x38, STRINGS)
    # Exact shipped CITY_ARENA callback bytecode: real progression state/event
    # calls, not a menu-side direct write to counters. Link addresses are
    # irrelevant to discovery; native VM execution is represented at its seam.
    jump = bytes.fromhex('011d80410000090501003d00011d80410000111c28000100011d00000000090501003e000f2f210000000421fcff041e0400')
    kill = bytes.fromhex('0a040000e700031d08000000011d000000000a040700cd000421fcff041e0400')
    simple = bytes.fromhex('011d803f0000111c440001000421fcff041e0400')
    # Original decompressed PS2 PK_V08_ELECTRO_FINALE script, functions
    # 100/98/97. These are the mission's actual debug commands, including
    # WIN v08's mission-state/event calls and the Electro script subroutine.
    win = bytes.fromhex('011d00400000111c840000000f2f12000000011de0420000011d803f0000011dad4300000a0423000800011d803f00000a0400000b010421fcff041e0400')
    maim = bytes.fromhex('081d0a006c00031d00000000011d204100000a040700cd000421fcff041e0400')
    stun = bytes.fromhex('0a040000e7000a040700440009050a005b000421fcff041e0400')
    reads_entry = bytes.fromhex('061dfcff0a04060000000421fcff041e0400')
    rows = [
        ('KILL HERO', 'kill_hero(debug_menu_entry)', kill),
        ('start progression before V08_ELECTRO_FINALE', 'start_to_level_V08(debug_menu_entry)', jump),
        ('toggle progression off', 'toggle_progression_off(debug_menu_entry)', simple),
        ('WIN v08', 'win_v08(debug_menu_entry)', win),
        ('MAIM ELECTRO', 'maim_electro(debug_menu_entry)', maim),
        ('STUN ELECTRO', 'stun_electro(debug_menu_entry)', stun),
        ('UNSUPPORTED VALUE CALLBACK', 'needs_entry(debug_menu_entry)', reads_entry),
    ]
    for i, (label, handler, code) in enumerate(rows):
        fn, data = 0x01301000 + i * 0x40, 0x01302000 + i * 0x100
        mem.w32(FUNCTIONS + i * 4, fn)
        mem.w32(fn, OBJECT if i < 3 else MISSION_OBJECT)
        mem.w32(fn + 4, M.name_hash(handler))
        mem.w32(fn + 12, 4); mem.w32(fn + 0x10, data)
        mem.w32(fn + 0x14, len(code)//2); mem.w32(fn + 0x1C, 2)
        mem.write(data, code)
        for j, text in enumerate((label, handler)):
            address = 0x01304000 + i * 256 + j * 128
            mem.write(address, text.encode() + b'\0')
            mem.w32(STRINGS + (i * 2 + j) * 4, address)
    mem.w32(OBJECT + 0x24, 3); mem.w32(MISSION_OBJECT + 0x24, len(rows) - 3)
    mem.w32(EXE + 0x3C, 2 * len(rows))
    # Matching label syntax alone does not authorize arbitrary callbacks.
    unknown = 0x01301000 + 6 * 0x40
    mem.w32(unknown + 0x14, len(kill)//2)
    mem.write(0x01302600, kill)
    assert not cpu.call(A.labels['dm_script_action_safe'], (unknown,))
    # Even an audited identity is rejected if its code reads the entry.
    mem.write(0x01302000, reads_entry + b'\0' * (len(kill) - len(reads_entry)))
    assert not cpu.call(A.labels['dm_script_action_safe'], (0x01301000,))
    mem.write(0x01302000, kill)
    # Wrong owner with the same full-name hash is not an audited command.
    mem.w32(OBJECT, 0x12345678)
    assert not cpu.call(A.labels['dm_script_action_safe'], (0x01301000,))
    mem.w32(OBJECT, 0x2958857E)
    calls = []
    def lookup(c):
        obj = c.r[4] & 0xffffffff
        assert obj in (OBJECT, MISSION_OBJECT)
        target = mem.u32(c.r[5] & 0xffffffff)
        first, count = mem.u32(obj + 0x20), mem.u32(obj + 0x24)
        c.r[2] = next((i for i in range(count)
                       if mem.u32(mem.u32(first + i * 4) + 4) == target), -1)
    def spawn(c):
        args = tuple(c.r[i] & 0xffffffff for i in (4, 5, 6))
        assert args[0] == (INSTANCE if args[1] < 0x013010C0 else MISSION_INSTANCE)
        assert mem.u32(args[2]) == 0, 'exact four-byte unused menu argument'
        calls.append(args[:2]); c.r[2] = 0x0130F000
    cpu.stubs[M.FIND_FUNC] = lookup
    cpu.stubs[M.TREE_NEXT] = lambda c: c.r.__setitem__(2, HEAD)
    cpu.stubs[M.ADD_THREAD] = spawn

    # Use the actual menu paths, then select each mission-authored action.
    if var('dm_active_menu'):
        tap(D.DMENU_TOGGLE)
    for i in (0, 3, 4, 5):
        tap(D.DMENU_TOGGLE); goto('Script'); tap(D.DMENU_SELECT)
        assert title() == 'Script'
        assert mem.u32(var('dm_active_menu') + D.M_COUNT) == 4
        goto(rows[i][0]); tap(D.DMENU_SELECT)
        assert calls[-1] == (INSTANCE if i < 3 else MISSION_INSTANCE, 0x01301000 + i * 0x40)
        assert not var('dm_active_menu'), 'native action selection closes menu'

    tap(D.DMENU_TOGGLE); goto('Progression'); tap(D.DMENU_SELECT)
    assert title() == 'Progression'
    assert mem.u32(var('dm_active_menu') + D.M_COUNT) == 2
    goto(rows[1][0]); tap(D.DMENU_SELECT)
    assert calls[-1] == (INSTANCE, 0x01301040)

    # Unload while unfocused: copied names remain valid and the old action
    # cannot call a function in a removed pack.
    tap(D.DMENU_TOGGLE); goto('Script'); tap(D.DMENU_SELECT)
    goto('WIN v08'); count = len(calls)
    label_address = mem.u32(mem.u32(var('dm_active_menu') + D.M_HIGHLIGHT))
    mem.w32(HEAD + 8, HEAD)
    tap(D.DMENU_SELECT)
    assert len(calls) == count
    assert mem.cstr(label_address) == 'WIN v08'
    tap(D.DMENU_TOGGLE)
    # Reuse of an executable address with another instance must also reject.
    mem.w32(HEAD + 8, NODE)
    tap(D.DMENU_TOGGLE); goto('Script'); tap(D.DMENU_SELECT); goto('WIN v08')
    mem.w32(MISSION_INSTANCES, MISSION_INSTANCE + 0x80)
    mem.w32(MISSION_INSTANCE + 0x80 + 0x2C, MISSION_OBJECT)
    tap(D.DMENU_SELECT); assert len(calls) == count
    tap(D.DMENU_TOGGLE)
    # No owner, ambiguous owner, suspended owner and unlinked function all
    # stay out of the executable action list.
    for first, next_instance, flags in ((0, 0, 0), (INSTANCE, INSTANCE + 0x80, 0), (INSTANCE, 0, 1)):
        mem.w32(INSTANCES, first); mem.w32(INSTANCE, next_instance)
        mem.w32(INSTANCE + 0x30, flags)
        mem.w32(MISSION_INSTANCES, 0)
        tap(D.DMENU_TOGGLE); goto('Script'); tap(D.DMENU_SELECT)
        assert mem.u32(var('dm_active_menu') + D.M_COUNT) == 0
        tap(D.DMENU_TOGGLE)
    mem.w32(INSTANCES, INSTANCE); mem.w32(INSTANCE, 0); mem.w32(INSTANCE + 0x30, 0)
    mem.w32(MISSION_INSTANCES, MISSION_INSTANCE)
    for i in range(len(rows)):
        mem.w32(0x01301000 + i * 0x40 + 0x1C, 0)
    tap(D.DMENU_TOGGLE); goto('Script'); tap(D.DMENU_SELECT)
    assert mem.u32(var('dm_active_menu') + D.M_COUNT) == 0
    tap(D.DMENU_TOGGLE)
    mem.w32(M.EXEC_MAP, 0)
    print('Script commands: callback binding, progression VM dispatch, unload and ABI guards passed')
