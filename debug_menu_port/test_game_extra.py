"""Behavior checks for packed NGL flags and Game/Progression additions."""
def run(ctx):
    D, mem, cpu = (ctx[k] for k in ('D', 'mem', 'cpu'))
    tap, goto, var = (ctx[k] for k in ('tap', 'goto', 'var'))
    state, log, stub = (ctx[k] for k in ('state', 'log', 'stub'))
    import dm_game_extra as X
    # Adjacent native bytes must survive every edit and clamp.
    mem.write(X.NGL_INFO - 1, bytes([0xA5, 0, 0, 0, 0x5A]))
    tap(D.DMENU_TOGGLE); goto('Debug Render'); tap(D.DMENU_SELECT)
    goto('NGL Debug'); tap(D.DMENU_SELECT)
    assert all('Hires Screenshot' not in row[4] for row in state['texts'])
    goto('Show Perf Info')
    tap(D.DMENU_RIGHT); tap(D.DMENU_RIGHT); tap(D.DMENU_RIGHT)
    assert mem.read(X.NGL_INFO - 1, 5) == bytes([0xA5, 2, 0, 0, 0x5A])
    goto('Show Perf Bar'); tap(D.DMENU_SELECT)
    assert mem.read(X.NGL_INFO - 1, 5) == bytes([0xA5, 2, 1, 0, 0x5A])
    # These NGL toggles keep the menu open. Return through the actual parents
    # instead of closing it and trying to navigate a null active menu.
    assert ctx['menu_title']() == 'NGL Debug'
    tap(D.DMENU_BACK); tap(D.DMENU_BACK)
    assert ctx['menu_title']() == 'Debug Menu'
    goto('Game'); tap(D.DMENU_SELECT)
    goto('Saved Game Settings'); tap(D.DMENU_SELECT)
    goto('STORY_MISSIONS_COMPLETED'); tap(D.DMENU_RIGHT)
    assert mem.u32(ctx['SETTINGS_OBJECT'] + 0x81C) == 1
    mem.w32(ctx['SETTINGS_OBJECT'] + 0x7B8, ctx['f2b'](-0.1))
    goto('HERO_HEALTH'); ctx['frame']((), show=True)
    assert 'HERO_HEALTH: -0.10' in [t[4] for t in state['texts']]
    mem.w32(ctx['SETTINGS_OBJECT'] + 0x7B8, ctx['f2b'](100.0))
    tap(D.DMENU_BACK)
    assert ctx['menu_title']() == 'Game'
    # Screenshot now lives in Game, not in the two-toggle NGL Debug menu.
    goto('Lores Screenshot'); tap(D.DMENU_SELECT)
    assert var('dm_active_menu') == 0
    assert mem.read(X.NGL_INFO - 1, 5) == bytes([0xA5, 2, 1, 1, 0x5A])
    tap(D.DMENU_TOGGLE); goto('Game'); tap(D.DMENU_SELECT)
    @stub(X.MONKEY_START)
    def start(c):
        log.append(('monkey_start',))
        mem.w32(X.MONKEY_RUNNING, 1)
    @stub(X.MONKEY_UNLOAD)
    def stop(c):
        log.append(('monkey_cleanup',))
    for addr, name in ((X.INPUT_STATE_CALLBACK, 'state_callback'), (X.INPUT_DELTA_CALLBACK, 'delta_callback')):
        cpu.stubs[addr] = lambda c, name=name: log.append((name, c.r[4], c.r[5]))
    mem.w32(X.MONKEY_RUNNING, 0)
    goto('Monkey Enabled'); tap(D.DMENU_SELECT)
    assert ('monkey_start',) in log and var('dm_active_menu') == 0
    tap(D.DMENU_TOGGLE); goto('Game'); tap(D.DMENU_SELECT); goto('Monkey Enabled'); tap(D.DMENU_SELECT)
    assert mem.u32(X.MONKEY_RUNNING) == 0
    assert ('state_callback', ctx['INPUT'], 0) in log
    assert ('delta_callback', ctx['INPUT'], 0) in log
    assert ('monkey_cleanup',) in log
    print('Game/NGL/Progression settings checks passed')
