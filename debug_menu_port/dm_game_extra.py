"""Retail-backed Game, AI, NGL and Progression menu additions.

NGL uses byte flags in the source debug-state block, not its per-frame copy:
0x5809A0 copies 0x6A10B8 -> 0x6A10D0; 0x580CBC reads +8/+9.
0x5815C4 consumes +0xA after rendering and clears the screenshot request.
"""
from asm5900 import Ref
from retail_settings import SETTINGS

MENUS = ('dm_ngl_menu', 'dm_progression_stats')
DYNAMIC_MENUS = ('dm_progression_stats',)
PROGRESSION = tuple(s for s in SETTINGS if s[1] >= 0x7CC or s[1] <= 0x74C)
MONKEY_RUNNING = 0x669078
MONKEY_START, MONKEY_UNLOAD = 0x1EB224, 0x1EB81C
INPUT_STATE_CALLBACK, INPUT_DELTA_CALLBACK = 0x32B5EC, 0x32B5F4
NGL_INFO, NGL_BAR, NGL_SCREENSHOT = 0x6A10C0, 0x6A10C1, 0x6A10C2


def emit_code(A, S, C):
    G = C['G']
    def call(target):
        A.jal(target); A.nop()

    # The native start installs both input callbacks. Stop mirrors the beta's
    # cleanup through verified retail setters, rather than only clearing its flag.
    f = A.func('h_monkey', saves=['s0', 's1'])
    call('dm_get')
    A.move('s0', 'v0')
    A.lw_abs('s1', G['input_mgr_instance'])
    A.beqz('s1', f.epi); A.nop()
    A.lw_abs('t0', G['os_dev_instance'])
    A.beqz('t0', f.epi); A.nop()
    A.beqz('s0', '.monkey_stop'); A.nop()
    call(MONKEY_START)
    call('dm_hide')
    f.ret()
    A.label('.monkey_stop')
    A.move('a0', 's1'); A.move('a1', 'zero')
    call(INPUT_STATE_CALLBACK)
    A.move('a0', 's1'); A.move('a1', 'zero')
    call(INPUT_DELTA_CALLBACK)
    A.sw_abs('zero', MONKEY_RUNNING)
    A.lw_abs('t0', G['os_dev_instance'])
    A.sw('zero', C['OSD_INTS'] + 9 * 4, 't0')
    call(MONKEY_UNLOAD)
    call('dm_hide')
    f.end()

    f = A.func('h_lores_screenshot', saves=[])
    call('dm_hide')
    A.li('t0', NGL_SCREENSHOT)
    A.addiu('t1', 'zero', 1)
    A.sb('t1', 0, 't0')
    f.end()

    f = A.func('p_progression_stats', saves=['s0', 's1', 's2'])
    A.la('a1', 'dm_progression_stats')
    A.la('a2', S('Progression Settings'))
    A.move('a3', 'zero'); call('dm_dyn_menu')
    A.lw_abs('t0', G['g_game_ptr'])
    A.beqz('t0', f.epi); A.nop()
    A.lw('s0', C['GAME_SETTINGS'], 't0')
    A.beqz('s0', f.epi); A.nop()
    A.la('s1', 'tbl_progression_stats')
    A.li('s2', len(PROGRESSION))
    A.label('.prog_loop')
    A.lw('a1', 0, 's1'); A.lw('a2', 8, 's1')
    call('dm_new_dyn')
    A.beqz('v0', f.epi); A.nop()
    A.lw('t0', 4, 's1'); A.addu('t0', 't0', 's0')
    A.sw('t0', C['E_VALUE'], 'v0')
    A.lw('t0', 12, 's1'); A.sw('t0', C['E_MAX'], 'v0')
    A.lw('t0', 16, 's1'); A.sw('t0', C['E_ID'], 'v0')
    A.la('a0', 'dm_progression_stats'); A.move('a1', 'v0')
    call('dm_add_entry')
    A.addiu('s1', 's1', 20); A.addiu('s2', 's2', -1)
    A.bnez('s2', '.prog_loop'); A.nop()
    f.end()


def emit_menus(A, S, C):
    G = C['G']
    def call(target):
        A.jal(target); A.nop()
    def submenu(parent, label, title, populate=None):
        if not populate:
            A.la('a0', label); A.la('a1', S(title)); A.move('a2', 'zero')
            call('dm_menu_reset')
        A.la('a0', parent)
        if populate:
            A.move('a1', 'zero'); A.la('a3', populate)
        else:
            A.la('a1', label); A.move('a3', 'zero')
        A.la('a2', S(title)); call('dm_add_sub')
    def entry(menu, name, typ, address=None, handler=None, maximum=None):
        A.la('a1', S(name)); A.li('a2', C[typ]); call('dm_new')
        if address is not None:
            A.li('t0', address); A.sw('t0', C['E_VALUE'], 'v0')
        if handler:
            A.la('t0', handler); A.sw('t0', C['E_HANDLER'], 'v0')
        if maximum is not None:
            A.li('t0', maximum); A.sw('t0', C['E_MAX'], 'v0')
        A.la('a0', menu); A.move('a1', 'v0'); call('dm_add_entry')
    def flags(menu, rows):
        # Native options are in a stable singleton; skip when unavailable.
        skip = A.newlabel('flags_missing')
        A.lw_abs('s3', G['os_dev_instance'])
        A.beqz('s3', skip); A.nop()
        for name, index, integer, maximum in rows:
            A.la('a1', S(name)); A.li('a2', C['T_INTP' if integer else 'T_BOOLP'])
            call('dm_new')
            A.addiu('t0', 's3', (C['OSD_INTS'] if integer else C['OSD_FLAGS']) + index * 4)
            A.sw('t0', C['E_VALUE'], 'v0')
            A.li('t0', maximum); A.sw('t0', C['E_MAX'], 'v0')
            A.la('a0', menu); A.move('a1', 'v0'); call('dm_add_entry')
        A.label(skip)

    submenu('dm_debug_render', 'dm_ngl_menu', 'NGL Debug')
    entry('dm_ngl_menu', 'Show Perf Info', 'T_BYTEINTP', NGL_INFO, maximum=2)
    entry('dm_ngl_menu', 'Show Perf Bar', 'T_BYTEP', NGL_BAR)


    entry('dm_game_menu', 'Monkey Enabled', 'T_BOOLP', MONKEY_RUNNING, 'h_monkey')
    entry('dm_game_menu', 'Lores Screenshot', 'T_ACTION', handler='h_lores_screenshot')


def emit_data(A, S, C):
    A.align(4); A.label('tbl_progression_stats')
    for name, offset, storage, maximum in PROGRESSION:
        A.word(Ref(S(name))); A.word(offset)
        A.word(C[{'int': 'T_INTP', 'bool': 'T_BOOLP', 'float': 'T_FLOATP'}[storage]])
        if storage == 'float':
            A.float32(float(maximum)); A.float32(0.1)
        else:
            A.word(maximum); A.word(0)


def emit_bss(A, C):
    pass
