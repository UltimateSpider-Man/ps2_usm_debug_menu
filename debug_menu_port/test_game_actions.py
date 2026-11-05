"""Exercise native-UI routing, auto-load lifecycle, and guarded Game actions."""
def run(ctx):
    import dm_game_actions as X
    D, A, mem, cpu, log = (ctx[k] for k in ('D', 'A', 'mem', 'cpu', 'log'))
    tap, goto, var, stub = (ctx[k] for k in ('tap', 'goto', 'var', 'stub'))
    GAME, WORLD, SETTINGS, INPUT, HERO = (ctx[k] for k in
        ('GAME', 'WORLD', 'SETTINGS_OBJECT', 'INPUT', 'HERO'))
    OSD = ctx['OSD']
    def tick():
        cpu.call(A.labels['dm_game_actions_tick'])
    def open_game():
        if var('dm_active_menu'):
            cpu.call(A.labels['dm_hide'])
        tap(D.DMENU_TOGGLE); goto('Game'); tap(D.DMENU_SELECT)
    def select(name):
        open_game(); goto(name); tap(D.DMENU_SELECT)
    def status():
        return mem.cstr(var('dm_ga_status'))

    open_game()
    entry = mem.u32(var('dm_active_menu') + D.M_FIRST)
    while entry:
        name = mem.cstr(mem.u32(entry + D.E_NAME))
        assert name != 'Last action' and '[not in retail]' not in name
        entry = mem.u32(entry + D.E_NEXT)
    goto('Report SLF Recall Timeouts')
    assert 'Report SLF Recall Timeouts: False' in [row[4] for row in ctx['state']['texts']]
    tap(D.DMENU_SELECT)
    assert var('dm_report_slf_recall_timeouts') == 1
    assert 'Report SLF Recall Timeouts: True' in [row[4] for row in ctx['state']['texts']]
    tap(D.DMENU_LEFT)
    assert var('dm_report_slf_recall_timeouts') == 0

    PAUSE, MENUS, DISPLAY, HOOKUP = 0x01600000, 0x01600100, 0x01600200, 0x01600400
    for addr, size in ((PAUSE, 0x100), (MENUS, 0x80), (DISPLAY, 0x100), (HOOKUP, 0x300)):
        mem.write(addr, bytes(size))
    mem.w32(X.PAUSE_PTR, PAUSE); mem.w32(PAUSE, MENUS)
    mem.w32(PAUSE+8, 0xffffffff); mem.w32(MENUS+0x18, DISPLAY)
    mem.w32(DISPLAY+0x2C, HOOKUP); mem.w32(0x6B7BC8, 0)
    mem.w32(GAME+D.GAME_SETTINGS, SETTINGS)
    game_state = {'value': 6, 'latest': 1}
    @stub(X.GET_GAME_STATE)
    def get_state(c):
        assert c.r[4] == GAME
        c.r[2] = game_state['value']
    @stub(X.PAUSE_ACTIVATE)
    def activate(c):
        assert tuple(c.r[4:7]) == (PAUSE, 6, 1)
        assert var('dm_active_menu') == 0
        mem.w32(PAUSE+8, 6); game_state['value'] = 7
        log.append(('card_ui',))
    @stub(X.SAVE_SCREEN_INIT)
    def save(c):
        assert c.r[4] == PAUSE
        log.append(('save_screen',)); mem.w32(HOOKUP+8, 18)
    @stub(X.LOAD_SCREEN_INIT)
    def load(c):
        assert c.r[4] == PAUSE
        log.append(('load_screen',)); mem.w32(HOOKUP+8, 17)
    @stub(X.FIND_LATEST)
    def latest(c):
        assert c.r[4] == SETTINGS
        log.append(('find_latest',)); c.r[2] = game_state['latest'] & 0xffffffff
    @stub(X.LOAD_FILE)
    def load_file(c):
        assert c.r[4] == HOOKUP
        log.append(('load_file', c.r[5])); mem.w32(HOOKUP+8, 13)
    def close_native():
        mem.w32(PAUSE+8, 0xffffffff); game_state['value'] = 6
        tick()

    log.clear(); select('Save Game')
    assert ('save_screen',) in log and ('load_screen',) not in log
    assert var('dm_active_menu') == 0
    close_native(); log.clear(); select('Load Game')
    assert ('load_screen',) in log and not var('dm_ga_auto_pause')
    close_native(); log.clear(); select('Attempt Auto Load')
    assert var('dm_ga_auto_pause') == PAUSE
    tick(); tick()
    assert not any(x[0] == 'find_latest' for x in log), log
    mem.w32(HOOKUP+8, 1); tick()
    assert ('load_file', 1) in log and not var('dm_ga_auto_pause')
    calls = len(log); tick(); assert len(log) == calls, 'auto-load must run once'
    close_native(); select('Attempt Auto Load'); log.clear()
    mem.w32(HOOKUP+8, 19); tick()  # no card / native error screen
    assert not var('dm_ga_auto_pause') and not log
    close_native(); select('Attempt Auto Load'); log.clear(); close_native()
    assert not var('dm_ga_auto_pause') and not log, 'leaving screen cancels pending load'
    mem.w32(X.PAUSE_PTR, 0); log.clear(); select('Save Game')
    assert var('dm_active_menu') and not log.count(('card_ui',))
    assert 'unavailable' in status()
    mem.w32(X.PAUSE_PTR, PAUSE)

    select('Invert Camera Look')
    assert mem.u32(SETTINGS+0x7C4) == 1 and mem.u32(SETTINGS+0x7C8) == 1
    select('Invert Camera Look')
    assert mem.u32(SETTINGS+0x7C4) == 0 and mem.u32(SETTINGS+0x7C8) == 0
    mem.w32(GAME+D.GAME_SETTINGS, 0); select('Invert Camera Look')
    assert status() == 'Game settings unavailable'
    mem.w32(GAME+D.GAME_SETTINGS, SETTINGS)

    PART6, PART5 = 0x01601000, 0x01601100
    mem.write(PART6, bytes(0x100)); mem.write(PART5, bytes(0x100)); mem.w32(PART6+0x18, 1)
    @stub(X.GET_PARTITION)
    def partition(c):
        c.r[2] = PART6 if c.r[4] == 6 else PART5 if c.r[4] == 5 else 0
    @stub(X.UNLOAD_DISTRICTS)
    def unload(c):
        assert c.r[4] == ctx['TERRAIN'] and var('dm_active_menu') == 0
        log.append(('unload_districts',))
    log.clear(); select('Toggle Unload All Districts')
    assert mem.u32(PART6+0x18) == 0 and ('unload_districts',) in log
    log.clear(); select('Toggle Unload All Districts')
    assert mem.u32(PART6+0x18) == 1 and ('unload_districts',) not in log
    @stub(X.PUSH_PROCESS)
    def push(c):
        assert tuple(c.r[4:6]) == (GAME, X.HIRES_PROCESS)
        log.append(('hires',))
    log.clear(); select('Hires Screenshot')
    assert ('hires',) in log and mem.u32(X.HIRES_WIDTH) == 1280 and mem.u32(X.HIRES_HEIGHT) == 960
    game_state['value'] = 8; log.clear(); select('Hires Screenshot')
    assert ('hires',) not in log and var('dm_active_menu')
    game_state['value'] = 6

    MOUSE, PAD, VTABLE, HV = 0x01602000, 0x01602100, 0x01602200, 0x01602300
    for p, n in ((MOUSE, 0x100), (PAD, 0x100), (VTABLE, 0x100), (HV, 0x400)):
        mem.write(p, bytes(n))
    mem.w32(X.MOUSELOOK_PTR, MOUSE); mem.w32(INPUT+0x3C, PAD); mem.w32(PAD+4, VTABLE)
    mem.w32(VTABLE+0x64, 0x007D0100); mem.w32(VTABLE+0x1C, 0x007D0120)
    mem.w32(HERO, HV); mem.w32(HV+0x384, 0x007D0140); mem.w32(HV+0x37C, 0x007D0160)
    mem.w32(GAME+D.GAME_USER_CAMERA, 1)
    connected = {'value': 1}
    cpu.stubs[0x007D0100] = lambda c: c.r.__setitem__(2, connected['value'])
    cpu.stubs[0x007D0120] = lambda c: c.r.__setitem__(2, 1000001)
    cpu.stubs[0x007D0140] = lambda c: log.append(('hero_control', 1))
    cpu.stubs[0x007D0160] = lambda c: log.append(('hero_control', 0))
    mem.w32(OSD+D.OSD_FLAGS+4*90, 0)
    select('User Camera on Controller 2')
    assert mem.u32(MOUSE+0x14) == 1000001 and ('hero_control', 1) in log
    select('User Camera on Controller 2')
    assert mem.u32(MOUSE+0x14) == 0xffffffff and ('hero_control', 0) in log
    connected['value'] = 0; select('User Camera on Controller 2')
    assert mem.u32(OSD+D.OSD_FLAGS+4*90) == 0 and 'disconnected' in status()
    mem.w32(GAME+D.GAME_USER_CAMERA, 0)
    cpu.call(A.labels['dm_hide'])
    print('Game action guards, camera, streaming, native card UI and auto-load checks passed')
