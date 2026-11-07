"""Verified retail Game actions, including the native memory-card screens.

Save/load use PauseMenuSystem's existing three-slot UI and its card callbacks.
Auto-load waits for that UI's validated load state, then selects the newest save.
The injected tick never services the memory card or replaces its observer.
"""
MENUS = ()
DYNAMIC_MENUS = ()
PAUSE_PTR = 0x69BC00                 # g_femanager + 0x18
PAUSE_ACTIVATE = 0x37EA4C
PAUSE_DEACTIVATE = 0x37EAC0          # closes the screen and calls game::unpause
SAVE_SCREEN_INIT, LOAD_SCREEN_INIT = 0x37ED60, 0x37ED80
FIND_LATEST, LOAD_FILE = 0x2DC098, 0x39CE88
GET_GAME_STATE, PUSH_PROCESS = 0x260C34, 0x26095C
GAME_PAUSE = 0x2AF71C
GAME_PAUSED = 0x1B0
HIRES_PROCESS, HIRES_WIDTH, HIRES_HEIGHT = 0x66C4F0, 0x66F2A0, 0x66F2A4
GET_PARTITION, UNLOAD_DISTRICTS = 0x28098C, 0x2A6D38
MOUSELOOK_PTR = 0x66EC4C


def emit_code(A, S, C):
    G = C['G']
    def call(addr):
        A.jal(addr); A.nop()
    def status(text):
        A.la('t0', S(text)); A.sw_abs('t0', 'dm_ga_status')
    def game_settings(out, fail):
        A.lw_abs(out, G['g_game_ptr'])
        A.beqz(out, fail); A.nop()
        A.lw(out, C['GAME_SETTINGS'], out)
        A.beqz(out, fail); A.nop()

    # Native Start activates transition 1 in state 7 (37E224..37E250), then
    # the FE switches to root screen 2 (PauseMenuSystem constructor order).
    # Deactivate performs the FE teardown, sound/rumble restore and unpause
    # (37EAC0..37EB18). Never dismiss screen 0 dialogs or memory-card screens.
    # Return 1 when the Select press was consumed, even if unpause was refused.
    f = A.func('dm_pause_to_debug', saves=['s0', 's1'])
    A.lw_abs('s0', G['g_game_ptr']); A.beqz('s0', '.pdbg_no'); A.nop()
    A.lw_abs('s1', PAUSE_PTR); A.beqz('s1', '.pdbg_no'); A.nop()
    A.lw('t0', 8, 's1'); A.addiu('t0', 't0', -1)
    A.sltiu('t0', 't0', 2); A.beqz('t0', '.pdbg_no'); A.nop()
    A.move('a0', 's0'); call(GET_GAME_STATE)
    A.li('t0', 7); A.bne('v0', 't0', '.pdbg_no'); A.nop()
    A.move('a0', 's1'); call(PAUSE_DEACTIVATE)
    A.li('t0', 30); A.sw_abs('t0', 'dm_pause_debug_pending')
    call('dm_pause_debug_tick')
    A.label('.pdbg_consumed'); A.li('v0', 1); f.ret()
    A.label('.pdbg_no'); A.move('v0', 'zero'); f.end()

    # Native pause process contains [7, 14]; unpause enters its end state 14
    # before the parent gameplay process (state 6) is restored next frame.
    # Wait for that handoff; do not put debug over a dialog or a refused exit.
    f = A.func('dm_pause_debug_tick', saves=['s0', 's1'])
    A.lw_abs('t0', 'dm_pause_debug_pending'); A.beqz('t0', f.epi); A.nop()
    A.addiu('t0', 't0', -1); A.sw_abs('t0', 'dm_pause_debug_pending')
    A.li('t0', 1); A.sw_abs('t0', 'dm_had_menu_this_frame')
    A.lw_abs('s0', G['g_game_ptr']); A.beqz('s0', '.pdt_cancel'); A.nop()
    A.lw_abs('s1', PAUSE_PTR); A.beqz('s1', '.pdt_cancel'); A.nop()
    A.move('a0', 's0'); call(GET_GAME_STATE)
    A.li('t0', 14); A.beq('v0', 't0', f.epi); A.nop()
    A.li('t0', 6); A.bne('v0', 't0', '.pdt_cancel'); A.nop()
    A.lw('t0', 8, 's1'); A.bgez('t0', '.pdt_cancel'); A.nop()
    A.sw_abs('zero', 'dm_pause_debug_pending'); call('dm_show'); f.ret()
    A.label('.pdt_cancel'); A.sw_abs('zero', 'dm_pause_debug_pending'); f.end()

    f = A.func('r_game_action_status', saves=[])
    A.move('a0', 'a1'); A.li('a1', 63); A.la('a2', S('%s'))
    A.lw_abs('a3', 'dm_ga_status')
    A.bnez('a3', '.ga_status_fmt'); A.nop()
    A.la('a3', S('Ready'))
    A.label('.ga_status_fmt'); call(G['snprintf'])
    f.end()

    f = A.func('h_ga_invert', saves=['s0'])
    call('dm_get'); A.move('s0', 'v0')
    game_settings('t0', '.ga_invert_missing')
    A.sw('s0', 0x7C4, 't0'); A.sw('s0', 0x7C8, 't0')
    status('Camera X/Y inversion updated'); f.ret()
    A.label('.ga_invert_missing'); status('Game settings unavailable'); f.end()

    # Refresh the combined toggle from the live settings (also editable elsewhere).
    f = A.func('r_ga_invert', saves=['s0', 's1'])
    A.move('s0', 'a0'); A.move('s1', 'a1')
    game_settings('t0', '.ga_invert_render_missing')
    A.lw('t1', 0x7C4, 't0'); A.lw('t2', 0x7C8, 't0')
    A.and_('t1', 't1', 't2'); A.sltu('t1', 'zero', 't1')
    A.sw('t1', C['E_VALUE'], 's0')
    A.la('a3', S('False')); A.beqz('t1', '.ga_invert_format'); A.nop()
    A.la('a3', S('True')); A.b('.ga_invert_format'); A.nop()
    A.label('.ga_invert_render_missing'); A.la('a3', S('Unavailable'))
    A.label('.ga_invert_format')
    A.move('a0', 's1'); A.li('a1', 63); A.la('a2', S('%s'))
    call(G['snprintf']); f.end()

    f = A.func('h_ga_controller2', saves=['s0', 's1', 's2', 's3'])
    A.move('s0', 'a0'); call('dm_get'); A.move('s1', 'v0')
    A.lw_abs('s2', MOUSELOOK_PTR)
    A.beqz('s2', '.ga_pad_missing'); A.nop()
    A.beqz('s1', '.ga_pad_off'); A.nop()
    A.lw_abs('t0', G['input_mgr_instance'])
    A.beqz('t0', '.ga_pad_missing'); A.nop()
    A.lw('s3', 0x3C, 't0'); A.beqz('s3', '.ga_pad_missing'); A.nop()
    A.lw('t0', 4, 's3'); A.beqz('t0', '.ga_pad_missing'); A.nop()
    A.lw('t1', 0x64, 't0'); A.beqz('t1', '.ga_pad_missing'); A.nop()
    A.lh('a0', 0x60, 't0'); A.addu('a0', 'a0', 's3')
    A.jalr('t1'); A.nop()
    A.beqz('v0', '.ga_pad_missing'); A.nop()
    A.lw('t0', 4, 's3'); A.lw('t1', 0x1C, 't0')
    A.beqz('t1', '.ga_pad_missing'); A.nop()
    A.lh('a0', 0x18, 't0'); A.addu('a0', 'a0', 's3')
    A.jalr('t1'); A.nop()
    A.sw('v0', 0x14, 's2'); A.b('.ga_pad_control'); A.nop()
    A.label('.ga_pad_off'); A.li('t0', -1); A.sw('t0', 0x14, 's2')
    A.label('.ga_pad_control')
    A.lw_abs('t0', G['g_game_ptr']); A.beqz('t0', '.ga_pad_done'); A.nop()
    A.lw('t0', C['GAME_USER_CAMERA'], 't0'); A.beqz('t0', '.ga_pad_done'); A.nop()
    A.lw_abs('t0', G['g_world_ptr']); A.beqz('t0', '.ga_pad_done'); A.nop()
    A.lw('t2', C['WORLD_HERO0'], 't0'); A.beqz('t2', '.ga_pad_done'); A.nop()
    A.lw('t0', 0, 't2'); A.beqz('t0', '.ga_pad_done'); A.nop()
    A.beqz('s1', '.ga_pad_disable_hero'); A.nop()
    A.lh('a0', 0x380, 't0'); A.lw('t1', 0x384, 't0')
    A.b('.ga_pad_virtual'); A.nop()
    A.label('.ga_pad_disable_hero')
    A.lh('a0', 0x378, 't0'); A.lw('t1', 0x37C, 't0')
    A.label('.ga_pad_virtual')
    A.beqz('t1', '.ga_pad_done'); A.nop()
    A.addu('a0', 'a0', 't2'); A.li('a1', 1); A.jalr('t1'); A.nop()
    A.label('.ga_pad_done'); status('User-camera controller updated'); f.ret()
    A.label('.ga_pad_missing')
    A.move('a0', 's0'); A.move('a1', 'zero'); call('dm_set')
    status('Controller 2 unavailable or disconnected'); f.end()

    f = A.func('h_ga_unload', saves=['s0', 's1', 's2'])
    A.lw_abs('t0', G['g_world_ptr']); A.beqz('t0', '.ga_unload_missing'); A.nop()
    A.lw('s0', C['WORLD_TERRAIN'], 't0'); A.beqz('s0', '.ga_unload_missing'); A.nop()
    A.li('a0', 6); call(GET_PARTITION); A.move('s1', 'v0')
    A.beqz('s1', '.ga_unload_missing'); A.nop()
    A.li('a0', 5); call(GET_PARTITION)
    A.beqz('v0', '.ga_unload_missing'); A.nop()
    A.lw('s2', 0x18, 's1'); call('dm_hide')
    A.beqz('s2', '.ga_unload_resume'); A.nop()
    A.move('a0', 's0'); call(UNLOAD_DISTRICTS)
    A.sw('zero', 0x18, 's1'); status('District streaming disabled'); f.ret()
    A.label('.ga_unload_resume'); A.li('t0', 1); A.sw('t0', 0x18, 's1')
    status('District streaming enabled'); f.ret()
    A.label('.ga_unload_missing'); status('Terrain or streaming partition unavailable'); f.end()

    f = A.func('h_ga_hires', saves=['s0'])
    A.lw_abs('s0', G['g_game_ptr']); A.beqz('s0', '.ga_hires_missing'); A.nop()
    A.move('a0', 's0'); call(GET_GAME_STATE)
    A.li('t0', 6); A.bne('v0', 't0', '.ga_hires_missing'); A.nop()
    call('dm_hide')
    # Two by two tiles: bounded memory use and an exact tile size.
    A.li('t0', 1280); A.sw_abs('t0', HIRES_WIDTH)
    A.li('t0', 960); A.sw_abs('t0', HIRES_HEIGHT)
    A.move('a0', 's0'); A.li('a1', HIRES_PROCESS); call(PUSH_PROCESS)
    status('Hires capture queued (PS2 host output)'); f.ret()
    A.label('.ga_hires_missing'); status('Hires capture requires active gameplay'); f.end()

    # E_ID: 0=save, 1=load, 2=auto-load. The native UI owns the three slots,
    # overwrite confirmations, progress, errors, and card insertion/removal.
    f = A.func('h_ga_card_screen', saves=['s0', 's1', 's2', 's3'])
    A.lw('s3', C['E_ID'], 'a0')
    A.lw_abs('s0', G['g_game_ptr']); A.beqz('s0', '.ga_card_missing'); A.nop()
    A.lw('t0', C['GAME_SETTINGS'], 's0'); A.beqz('t0', '.ga_card_missing'); A.nop()
    A.lw_abs('t0', G['g_world_ptr']); A.beqz('t0', '.ga_card_missing'); A.nop()
    A.lw('t0', C['WORLD_HERO0'], 't0'); A.beqz('t0', '.ga_card_missing'); A.nop()
    A.lw_abs('s1', PAUSE_PTR); A.beqz('s1', '.ga_card_missing'); A.nop()
    A.lw('t0', 8, 's1'); A.bgez('t0', '.ga_card_paused'); A.nop()
    A.lw('t0', 0, 's1'); A.beqz('t0', '.ga_card_missing'); A.nop()
    A.lw('s2', 0x18, 't0'); A.beqz('s2', '.ga_card_missing'); A.nop()
    A.lw('t0', 0x2C, 's2'); A.beqz('t0', '.ga_card_missing'); A.nop()
    A.move('a0', 's0'); call(GET_GAME_STATE)
    A.li('t0', 6); A.bne('v0', 't0', '.ga_card_busy'); A.nop()
    A.lw('t0', GAME_PAUSED, 's0'); A.bnez('t0', '.ga_card_busy'); A.nop()
    A.lw_abs('t0', 0x6B7BC8); A.bnez('t0', '.ga_card_blocked'); A.nop()
    call('dm_hide')
    # Native Start pauses first (37E228), then activates the UI with a2=0
    # (37E24C). The pause-process initializer hides old FE widgets: running
    # it after display activation erases the title and slot list on reopen.
    A.move('a0', 's0'); call(GAME_PAUSE)
    A.lw('t0', GAME_PAUSED, 's0'); A.beqz('t0', '.ga_card_busy'); A.nop()
    # Retail root handlers (38FA5C / 38FA94) initialize the mode BEFORE
    # activating the display. OnActivate builds the title and slot widgets
    # from that mode; doing it first leaves the ready screen blank.
    A.beqz('s3', '.ga_card_save'); A.nop()
    A.move('a0', 's1'); call(LOAD_SCREEN_INIT)
    A.b('.ga_card_activate'); A.nop()
    A.label('.ga_card_save'); A.move('a0', 's1'); call(SAVE_SCREEN_INIT)
    A.label('.ga_card_activate')
    A.move('a0', 's1'); A.li('a1', 6); A.move('a2', 'zero'); call(PAUSE_ACTIVATE)
    A.lw('t0', 8, 's1'); A.li('t1', 6)
    A.bne('t0', 't1', '.ga_card_paused'); A.nop()
    A.li('t0', 2); A.bne('s3', 't0', '.ga_card_ready'); A.nop()
    A.sw_abs('s1', 'dm_ga_auto_pause')
    A.lw('t0', 0x2C, 's2'); A.sw_abs('t0', 'dm_ga_auto_hookup')
    A.label('.ga_card_ready'); status('Native memory-card screen opened'); f.ret()
    A.label('.ga_card_busy'); status('Wait for gameplay and close the pause screen'); f.ret()
    A.label('.ga_card_paused'); status('Close the native pause or memory-card screen'); f.ret()
    A.label('.ga_card_blocked'); status('Wait for the native memory-card operation to finish'); f.ret()
    A.label('.ga_card_missing'); status('Memory-card screen unavailable'); f.end()

    # Called by hook_tick. PauseMenuSystem already services MemoryUnitManager.
    # A user leaving the native screen or any terminal error cancels auto-load.
    f = A.func('dm_game_actions_tick', saves=['s0', 's1'])
    A.lw_abs('s0', 'dm_ga_auto_pause'); A.beqz('s0', f.epi); A.nop()
    A.lw_abs('t0', PAUSE_PTR); A.bne('s0', 't0', '.ga_auto_cancel'); A.nop()
    A.lw('t0', 8, 's0'); A.li('t1', 6)
    A.bne('t0', 't1', '.ga_auto_cancel'); A.nop()
    A.lw_abs('s1', 'dm_ga_auto_hookup'); A.beqz('s1', '.ga_auto_cancel'); A.nop()
    A.lw('t0', 8, 's1'); A.li('t1', 17)
    A.beq('t0', 't1', f.epi); A.nop()  # reading card
    A.li('t1', 18); A.beq('t0', 't1', f.epi); A.nop()  # checking card
    A.li('t1', 1); A.bne('t0', 't1', '.ga_auto_cancel'); A.nop()
    game_settings('s0', '.ga_auto_cancel')
    A.lbu('t0', 0x916, 's0'); A.bnez('t0', '.ga_auto_cancel'); A.nop()
    A.move('a0', 's0'); call(FIND_LATEST)
    A.sltiu('t0', 'v0', 3); A.beqz('t0', '.ga_auto_cancel'); A.nop()
    A.move('a1', 'v0'); A.move('a0', 's1')
    A.sw_abs('zero', 'dm_ga_auto_pause'); A.sw_abs('zero', 'dm_ga_auto_hookup')
    call(LOAD_FILE); status('Loading newest validated save'); f.ret()
    A.label('.ga_auto_cancel')
    A.sw_abs('zero', 'dm_ga_auto_pause'); A.sw_abs('zero', 'dm_ga_auto_hookup')
    status('Auto load ended; see the memory-card screen'); f.end()


def emit_menus(A, S, C):
    def call(addr):
        A.jal(addr); A.nop()
    def entry(menu, text, typ='T_ACTION', handler=None, render=None, index=0, value_label=None):
        A.la('a1', S(text)); A.li('a2', C[typ]); call('dm_new')
        skip = A.newlabel('ga_entry_full')
        A.beqz('v0', skip); A.nop()
        if handler:
            A.la('t0', handler); A.sw('t0', C['E_HANDLER'], 'v0')
        if render:
            A.la('t0', render); A.sw('t0', C['E_RENDER'], 'v0')
        A.li('t0', index); A.sw('t0', C['E_ID'], 'v0')
        if value_label:
            A.la('t0', value_label); A.sw('t0', C['E_VALUE'], 'v0')
        elif typ == 'T_BOOLP':
            A.lw_abs('t0', C['G']['os_dev_instance'])
            A.beqz('t0', skip); A.nop()
            A.addiu('t0', 't0', C['OSD_FLAGS'] + 4*90)
            A.sw('t0', C['E_VALUE'], 'v0')
        A.la('a0', menu); A.move('a1', 'v0'); call('dm_add_entry')
        A.label(skip)
    entry('dm_game_menu', 'Invert Camera Look', 'T_BOOL', 'h_ga_invert', 'r_ga_invert')
    entry('dm_game_menu', 'User Camera on Controller 2', 'T_BOOLP', 'h_ga_controller2')
    entry('dm_game_menu', 'Toggle Unload All Districts', handler='h_ga_unload')
    entry('dm_game_menu', 'Save Game', handler='h_ga_card_screen', index=0)
    entry('dm_game_menu', 'Load Game', handler='h_ga_card_screen', index=1)
    entry('dm_game_menu', 'Attempt Auto Load', handler='h_ga_card_screen', index=2)
    entry('dm_game_menu', 'Hires Screenshot', handler='h_ga_hires')
    entry('dm_game_menu', 'Report SLF Recall Timeouts', 'T_BOOLP',
          value_label='dm_report_slf_recall_timeouts')


def emit_data(A, S, C):
    pass


def emit_bss(A, C):
    for name in ('dm_ga_status', 'dm_ga_auto_pause', 'dm_ga_auto_hookup',
                 'dm_pause_debug_pending'):
        A.align(4); A.label(name); A.word(0)
