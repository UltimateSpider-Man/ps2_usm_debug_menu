"""Exercise real emitted controller input and pause/map hooks."""
import dm_build as D
from emu import Mem, CPU, f2b, b2f


def run():
    A, blob = D.build()
    mem = Mem(); mem.write(D.BASE, blob)
    mem.write(0x01000000, bytes(0x10000))
    mem.write(0x01E00000, bytes(0x100000))
    cpu = CPU(mem, D.BASE, A.labels['dm_end'])
    held, events = {}, []
    GAME, INPUT = 0x01000000, 0x01000400
    mem.w32(D.G['g_game_ptr'], GAME)
    mem.w32(D.G['input_mgr_instance'], INPUT)
    mem.w32(A.labels['dm_built'], 1)
    root = A.labels['dm_root_menu']
    cpu.stubs[D.G['get_control_state']] = lambda c: c.f.__setitem__(0, f2b(held.get(c.r[5], 0)))
    cpu.stubs[D.G['enable_physics']] = lambda c: mem.w32(GAME + D.GAME_STOP_PHYSICS, not c.r[5])
    def pause(c):
        events.append('pause'); c.f[0] = f2b(1)
    cpu.stubs[D.G['get_control_delta']] = pause
    cpu.stubs[D.G['igo_zoom_map_on_select']] = lambda c: events.append('map')
    def var(name): return mem.u32(A.labels[name])
    def frame(*buttons, dt=.02):
        held.clear(); held.update({b: 1 for b in buttons})
        cpu.call(A.labels['dm_frame_advance'], fargs=(dt,))
    def hooks(blocked):
        events.clear()
        cpu.call(A.labels['hook_pause'], args=(INPUT, 0x36, -1))
        assert b2f(cpu.f[0]) == (0 if blocked else 1)
        cpu.call(A.labels['hook_map'], args=(0x01000800,))
        assert events == ([] if blocked else ['pause', 'map']), events
    SELECT, START = D.DMENU_TOGGLE, D.DMENU_FOCUS_TOGGLE
    frame(SELECT)
    assert var('dm_active_menu') == 0, 'Select alone must retain the native map'
    hooks(False)
    frame(); frame(START)
    assert var('dm_active_menu') == 0
    hooks(False)
    frame(); frame(START, SELECT)
    assert var('dm_active_menu') == root and var('dm_has_focus') == 1
    hooks(True)
    for _ in range(15):
        frame(START, SELECT, dt=.1)
        assert var('dm_active_menu') == root and var('dm_has_focus') == 1
    # Chord release must not turn the still-held Start into a focus event.
    frame(START); assert var('dm_has_focus') == 1
    frame(); frame(START)
    assert var('dm_has_focus') == 0 and mem.u32(GAME + D.GAME_STOP_PHYSICS) == 0
    for _ in range(10):
        frame(START, dt=.1); assert var('dm_has_focus') == 0
    frame(); frame(START)
    assert var('dm_has_focus') == 1 and mem.u32(GAME + D.GAME_STOP_PHYSICS) == 1
    frame(); frame(START); frame()
    assert var('dm_has_focus') == 0
    # The close chord also works from the running/visible state.
    frame(START, SELECT)
    assert var('dm_active_menu') == 0
    hooks(True)
    frame(SELECT); hooks(True)
    frame(); hooks(False)
    frame(SELECT); assert var('dm_active_menu') == 0; hooks(False)
    # A previously stopped game retains its stop state on exit.
    frame(); mem.w32(GAME + D.GAME_STOP_PHYSICS, 1)
    frame(SELECT, START); frame(); frame(START); frame()
    assert var('dm_has_focus') == 0 and mem.u32(GAME + D.GAME_STOP_PHYSICS) == 1
    frame(SELECT, START); frame()
    assert var('dm_active_menu') == 0 and mem.u32(GAME + D.GAME_STOP_PHYSICS) == 1

    # Start opens native pause; a NEW Select press replaces that root screen
    # with focused debug, and Start then resumes gameplay rather than pause.
    X = D.dm_game_actions
    PAUSE = 0x01000800
    mem.w32(X.PAUSE_PTR, PAUSE)
    native = {'state': 6}
    calls = []
    def game_state(c):
        assert c.r[4] == GAME
        c.r[2] = native['state']
    def deactivate(c):
        assert c.r[4] == PAUSE and var('dm_active_menu') == 0
        calls.append('deactivate')
        mem.w32(PAUSE + 8, 0xffffffff)
        native['state'] = 6
    cpu.stubs[X.GET_GAME_STATE] = game_state
    cpu.stubs[X.PAUSE_DEACTIVATE] = deactivate
    mem.w32(GAME + D.GAME_STOP_PHYSICS, 0)
    mem.w32(PAUSE + 8, 0xffffffff)
    frame(START); hooks(False)
    native['state'] = 7; mem.w32(PAUSE + 8, 2)
    frame(); frame(SELECT)
    assert calls == ['deactivate'], 'Select in pause must close the native screen'
    assert native['state'] == 6 and mem.u32(PAUSE + 8) == 0xffffffff
    assert var('dm_active_menu') == root and var('dm_has_focus') == 1
    hooks(True)
    for _ in range(5): frame(SELECT, dt=.1)
    assert calls == ['deactivate'] and var('dm_has_focus') == 1
    frame(); frame(START); frame()
    assert var('dm_has_focus') == 0 and mem.u32(GAME + D.GAME_STOP_PHYSICS) == 0
    frame(START, SELECT); frame(); hooks(False)
    # Dialogs/card screens and gameplay Select keep their native behavior.
    for screen, state in ((0, 7), (3, 7), (6, 7), (2, 6), (0xffffffff, 6)):
        mem.w32(PAUSE + 8, screen); native['state'] = state
        frame(SELECT); frame()
        assert var('dm_active_menu') == 0 and calls == ['deactivate']
        assert mem.u32(PAUSE + 8) == screen
    # An existing Select hold must not enter debug when pause becomes visible.
    frame(SELECT)
    mem.w32(PAUSE + 8, 2); native['state'] = 7
    frame(SELECT, dt=.5)
    assert var('dm_active_menu') == 0 and calls == ['deactivate']
    # A refused unpause cannot leave debug drawn over a still-active pause UI.
    def refuse(c):
        assert c.r[4] == PAUSE
        calls.append('refused')
    cpu.stubs[X.PAUSE_DEACTIVATE] = refuse
    frame(); frame(SELECT)
    assert var('dm_active_menu') == 0 and native['state'] == 7
    assert calls == ['deactivate', 'refused']; hooks(True)
    frame(SELECT, dt=.5); assert calls == ['deactivate', 'refused']
    # The simultaneous combo while paused uses the same native cleanup.
    cpu.stubs[X.PAUSE_DEACTIVATE] = deactivate
    mem.w32(PAUSE + 8, 1)  # also accept Select during the opening transition
    frame(); frame(START, SELECT)
    assert var('dm_active_menu') == root and var('dm_has_focus') == 1
    assert calls == ['deactivate', 'refused', 'deactivate']
    frame(); frame(START, SELECT); frame()
    assert var('dm_active_menu') == 0 and native['state'] == 6
    # Retail unpause first enters end state 14; wait for parent gameplay 6.
    def resume(c):
        assert c.r[4] == PAUSE
        mem.w32(PAUSE + 8, 0xffffffff); native['state'] = 14
    cpu.stubs[X.PAUSE_DEACTIVATE] = resume
    mem.w32(PAUSE + 8, 2); native['state'] = 7
    frame(SELECT)
    assert var('dm_active_menu') == 0 and var('dm_pause_debug_pending') > 0
    frame(); hooks(True)
    assert var('dm_active_menu') == 0
    native['state'] = 6; frame()
    assert var('dm_active_menu') == root and var('dm_has_focus') == 1
    assert var('dm_pause_debug_pending') == 0
    frame(START, SELECT); frame()
    # An interrupted resume into a dialog must cancel instead of hiding it.
    mem.w32(PAUSE + 8, 2); native['state'] = 7
    frame(SELECT); native['state'] = 7; mem.w32(PAUSE + 8, 0)
    frame()
    assert var('dm_active_menu') == 0 and var('dm_pause_debug_pending') == 0
    print('START/SELECT TESTS PASSED; steps:', cpu.steps)


if __name__ == '__main__':
    run()
