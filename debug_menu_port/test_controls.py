"""R5900 input/accelerator and signed integer boundary regression scenarios."""
import dm_build as D
from emu import Mem, CPU, f2b, b2f, s32


def run():
    A, blob = D.build()
    mem = Mem(); mem.write(D.BASE, blob)
    mem.write(0x01000000, bytes(0x10000)); mem.write(0x01E00000, bytes(0x100000))
    cpu = CPU(mem, D.BASE, A.labels['dm_end'])
    def call(name, *args, dt=None):
        return cpu.call(A.labels[name], args=args, fargs=() if dt is None else (dt,))
    def var(name): return mem.u32(A.labels[name])
    def put(name, value): mem.w32(A.labels[name], value)
    held = {}
    def control(c): c.f[0] = f2b(held.get(c.r[5], 0))
    cpu.stubs[D.G['get_control_state']] = control
    GAME, INPUT = 0x01000000, 0x01000400
    mem.w32(D.G['g_game_ptr'], GAME); mem.w32(D.G['input_mgr_instance'], INPUT)
    def physics(c): mem.w32(GAME + D.GAME_STOP_PHYSICS, 0 if c.r[5] else 1)
    cpu.stubs[D.G['enable_physics']] = physics
    put('dm_built', 1)
    ROOT = A.labels['dm_root_menu']; CHILD = 0x01001000
    SUB = 0x01001100; ENTRIES = 0x01002000; FLOAT = 0x01004000
    mem.w32(ROOT + D.M_FIRST, SUB); mem.w32(ROOT + D.M_LAST, SUB); mem.w32(ROOT + D.M_COUNT, 1)
    mem.w32(SUB + D.E_TYPE, D.T_SUB); mem.w32(SUB + D.E_SUBMENU, CHILD)
    mem.w32(CHILD + D.M_FIRST, ENTRIES); mem.w32(CHILD + D.M_LAST, ENTRIES + 49 * D.E_SIZE)
    mem.w32(CHILD + D.M_COUNT, 50)
    for i in range(50):
        e = ENTRIES + i * D.E_SIZE
        mem.w32(e + D.E_TYPE, D.T_INT); mem.w32(e + D.E_MIN, 0x80000000)
        mem.w32(e + D.E_MAX, 0x7FFFFFFF)
        mem.w32(e + D.E_NEXT, e + D.E_SIZE if i < 49 else 0)
        mem.w32(e + D.E_PREV, e - D.E_SIZE if i else 0)
    def frame(buttons=(), dt=.02, axes=None):
        held.clear(); held.update({b: 1 for b in buttons}); held.update(axes or {})
        call('dm_frame_advance', dt=dt)
    def tap(*buttons):
        if buttons == (D.DMENU_TOGGLE,):
            buttons = (D.DMENU_TOGGLE, D.DMENU_FOCUS_TOGGLE)
        frame(buttons); frame()
    def selected(): return mem.u32(CHILD + D.M_HIGHLIGHT)

    # Start + Select opens, X enters, d-pad/analog navigate, L1/R1 page and Back returns.
    tap(D.DMENU_TOGGLE); assert var('dm_active_menu') == ROOT and var('dm_has_focus') == 1
    tap(D.DMENU_SELECT); assert var('dm_active_menu') == CHILD and selected() == ENTRIES
    tap(D.DMENU_DOWN); assert selected() == ENTRIES + D.E_SIZE
    tap(D.DMENU_UP); assert selected() == ENTRIES
    frame(axes={D.DMENU_UD: 1}); frame(); assert selected() == ENTRIES + D.E_SIZE
    frame(axes={D.DMENU_UD: -1}); frame(); assert selected() == ENTRIES
    tap(D.DMENU_PGDN); assert selected() == ENTRIES + D.VISIBLE_LINES * D.E_SIZE
    tap(D.DMENU_PGUP); assert selected() == ENTRIES
    tap(D.DMENU_BACK); assert var('dm_active_menu') == ROOT
    # Native FE Circle is control 0x51; Triangle/shared Back alone must not
    # close root. A press that begins in a child returns only one level.
    CIRCLE = 0x51
    tap(D.DMENU_BACK); assert var('dm_active_menu') == ROOT
    tap(CIRCLE)
    assert var('dm_active_menu') == 0, 'Circle at the root must close debug'
    assert var('dm_has_focus') == 0 and mem.u32(GAME + D.GAME_STOP_PHYSICS) == 0
    tap(CIRCLE); assert var('dm_active_menu') == 0, 'Circle must not open debug'
    tap(D.DMENU_TOGGLE); tap(D.DMENU_SELECT)
    frame((CIRCLE, D.DMENU_BACK))
    assert var('dm_active_menu') == ROOT, 'Circle in a child must only go Back'
    for _ in range(8):
        frame((CIRCLE, D.DMENU_BACK), dt=.1)
        assert var('dm_active_menu') == ROOT, 'held Circle must not close after Back'
    frame(); frame((CIRCLE,))
    assert var('dm_active_menu') == 0 and var('dm_had_menu_this_frame') == 1
    frame()
    tap(D.DMENU_TOGGLE); tap(D.DMENU_FOCUS_TOGGLE)
    assert var('dm_has_focus') == 0 and mem.u32(GAME + D.GAME_STOP_PHYSICS) == 0
    tap(CIRCLE)
    assert var('dm_active_menu') == 0, 'Circle must also close visible unfocused root'
    mem.w32(GAME + D.GAME_STOP_PHYSICS, 1)
    tap(D.DMENU_TOGGLE); tap(CIRCLE)
    assert var('dm_active_menu') == 0 and mem.u32(GAME + D.GAME_STOP_PHYSICS) == 1
    mem.w32(GAME + D.GAME_STOP_PHYSICS, 0)
    tap(D.DMENU_TOGGLE)
    tap(D.DMENU_SELECT); assert var('dm_active_menu') == CHILD

    # Float accelerator exactly follows beta's virtual SELECT/X event, using
    # step 0.3 * scale 30 = 9.0. X alone leaves a numeric value unchanged.
    mem.w32(ENTRIES + D.E_TYPE, D.T_FLOATP); mem.w32(ENTRIES + D.E_VALUE, FLOAT)
    mem.w32(ENTRIES + D.E_ID, f2b(.3)); mem.w32(ENTRIES + D.E_POPULATE, f2b(30))
    mem.w32(ENTRIES + D.E_MIN, f2b(-100)); mem.w32(ENTRIES + D.E_MAX, f2b(100))
    mem.w32(FLOAT, f2b(0))
    tap(D.DMENU_RIGHT); assert abs(b2f(mem.u32(FLOAT)) - .3) < .00001
    tap(D.DMENU_SELECT); assert abs(b2f(mem.u32(FLOAT)) - .3) < .00001
    tap(D.DMENU_SELECT, D.DMENU_RIGHT); assert abs(b2f(mem.u32(FLOAT)) - 9.3) < .00001
    tap(D.DMENU_SELECT, D.DMENU_LEFT); assert abs(b2f(mem.u32(FLOAT)) - .3) < .00001
    frame((D.DMENU_SELECT, D.DMENU_RIGHT)); v = b2f(mem.u32(FLOAT))
    frame((D.DMENU_SELECT, D.DMENU_RIGHT), dt=.1)
    frame((D.DMENU_SELECT, D.DMENU_RIGHT), dt=.1); assert b2f(mem.u32(FLOAT)) == v
    frame((D.DMENU_SELECT, D.DMENU_RIGHT), dt=.06); assert abs(b2f(mem.u32(FLOAT)) - (v + 9)) < .00001
    frame((D.DMENU_SELECT, D.DMENU_RIGHT), dt=.05); assert abs(b2f(mem.u32(FLOAT)) - (v + 18)) < .00001
    frame()
    # Holding X between virtual repeat events does not invent a different
    # modifier scheme from the recorded/native PS2 behavior.
    frame((D.DMENU_SELECT,)); v = b2f(mem.u32(FLOAT))
    frame((D.DMENU_SELECT, D.DMENU_RIGHT), dt=.02)
    assert abs(b2f(mem.u32(FLOAT)) - (v + .3)) < .00001
    frame()
    # Zero scale metadata selects the beta constructor's default of ten.
    mem.w32(ENTRIES + D.E_POPULATE, 0); mem.w32(ENTRIES + D.E_ID, f2b(.1))
    mem.w32(FLOAT, f2b(0)); tap(D.DMENU_SELECT, D.DMENU_RIGHT)
    assert b2f(mem.u32(FLOAT)) == 1
    mem.w32(FLOAT, f2b(99.9)); tap(D.DMENU_SELECT, D.DMENU_RIGHT)
    assert b2f(mem.u32(FLOAT)) == 100
    mem.w32(FLOAT, f2b(-99.9)); tap(D.DMENU_SELECT, D.DMENU_LEFT)
    assert b2f(mem.u32(FLOAT)) == -100

    # START releases game focus without closing; unfocused input cannot edit.
    tap(D.DMENU_FOCUS_TOGGLE)
    assert var('dm_active_menu') == CHILD and var('dm_has_focus') == 0
    assert mem.u32(GAME + D.GAME_STOP_PHYSICS) == 0
    before = mem.u32(FLOAT); tap(D.DMENU_RIGHT); assert mem.u32(FLOAT) == before
    tap(CIRCLE); assert var('dm_active_menu') == CHILD, 'unfocused child keeps gameplay input'
    tap(D.DMENU_FOCUS_TOGGLE); assert var('dm_has_focus') == 1
    assert mem.u32(GAME + D.GAME_STOP_PHYSICS) == 1
    tap(D.DMENU_TOGGLE); assert var('dm_active_menu') == 0
    assert mem.u32(GAME + D.GAME_STOP_PHYSICS) == 0

    # Signed values retain the low word only after saturating in 64-bit space.
    for typ in (D.T_INT, D.T_INTP):
        mem.w32(ENTRIES + D.E_TYPE, typ)
        mem.w32(ENTRIES + D.E_MIN, 0x80000000); mem.w32(ENTRIES + D.E_MAX, 0x7FFFFFFF)
        target = ENTRIES + D.E_VALUE if typ == D.T_INT else FLOAT
        if typ == D.T_INTP: mem.w32(ENTRIES + D.E_VALUE, FLOAT)
        for initial, direction, expected in ((2147483647, 1, 2147483647),
                                             (-2147483648, -1, -2147483648),
                                             (2147483646, 1, 2147483647),
                                             (-2147483647, -1, -2147483648),
                                             (16777216, 1, 16777217),
                                             (-16777216, -1, -16777217)):
            mem.w32(target, initial); call('dm_on_change', ENTRIES, direction)
            assert s32(mem.u32(target)) == expected, (typ, initial, direction, s32(mem.u32(target)))
    print('CONTROL TESTS PASSED; steps:', cpu.steps)


if __name__ == '__main__':
    run()
