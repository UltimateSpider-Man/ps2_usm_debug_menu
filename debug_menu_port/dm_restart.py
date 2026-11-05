"""City restart through the retained retail LoadExecPS2 boot path.

Native reference: reboot routine 0x38F37C. Arguments add the selected scene and
current hero to its skip_to_loading option. All preflight work precedes teardown.
"""
from asm5900 import Ref

MENUS = ()
DYNAMIC_MENUS = ()
APP_NAME, BOOT_MODE, KERNEL_ARGS = 0x69B9D4, 0x6701D8, 0x6BB160
SOUND_SLOTS, PACKER = 0x66CA74, 0x698FA8
OPEN, CLOSE, LOAD_EXEC, EXIT, KPRINTF = 0x60ADF8, 0x60B080, 0x60CAD8, 0x60CB20, 0x609508
PATH_CAPACITY = 256
CLEANUP = (
    (0x28B2C0, ()), (0x28A470, ()), (0x57E698, ()),
    (0x5EC338, (0, 0, 0)), (0x5EF988, ()), (0x5EFBE8, ()),
    (0x5EEF88, (0,)), (0x5EF4E8, (0,)), (0x5ED6A8, ()), (0x609878, ()),
)


def emit_code(A, S, C):
    G = C['G']
    def call(target):
        A.jal(target); A.nop()
    def error(text, label):
        A.label(label); A.la('t0', S(text)); A.sw_abs('t0', 'dm_city_restart_error')
        A.move('v0', 'zero')

    # a0=dest, a1=source, a2=capacity; v0=nonempty length, or 0 on failure.
    f = A.func('dm_restart_copy', saves=['s0', 's1', 's2'])
    A.move('s0', 'a0'); A.move('s1', 'a1'); A.move('s2', 'a2')
    A.move('a0', 's1'); A.move('a1', 's2'); call('dm_catalog_ram')
    A.beqz('v0', f.epi); A.nop()
    A.move('v0', 'zero')
    A.label('.restart_copy')
    A.addu('t0', 's1', 'v0'); A.lbu('t1', 0, 't0')
    A.addu('t0', 's0', 'v0'); A.sb('t1', 0, 't0')
    A.beqz('t1', f.epi); A.nop()
    A.addiu('v0', 'v0', 1); A.sltu('t2', 'v0', 's2')
    A.bnez('t2', '.restart_copy'); A.nop()
    A.addiu('t0', 's2', -1); A.addu('t0', 's0', 't0'); A.sb('zero', 0, 't0')
    A.move('v0', 'zero'); f.end()

    # a0=entry. Copy every argument before an unload can invalidate its owner.
    f = A.func('dm_city_restart_prepare', saves=['s0', 's1', 's2'])
    A.move('s0', 'a0'); A.sw_abs('zero', 'dm_city_restart_error')
    A.lw_abs('t0', 'dm_hero_status'); A.bnez('t0', '.city_hero_busy'); A.nop()
    A.lw('s1', C['E_ID'], 's0')
    A.move('a0', 's1'); call('dm_catalog_name')
    A.beqz('v0', '.city_bad_scene'); A.nop()
    A.move('a0', 's1'); call('dm_catalog_has_pack')
    A.beqz('v0', '.city_bad_scene'); A.nop()
    A.la('a0', 'dm_restart_scene'); A.move('a1', 's1'); A.li('a2', 32); call('dm_restart_copy')
    A.beqz('v0', '.city_bad_scene'); A.nop()
    A.lw_abs('s0', G['g_game_ptr']); A.andi('t0', 's0', 3)
    A.bnez('t0', '.city_bad_hero'); A.nop()
    A.move('a0', 's0'); A.li('a1', C['GAME_SETTINGS'] + 4); call('dm_catalog_ram')
    A.beqz('v0', '.city_bad_hero'); A.nop()
    A.lw('t0', C['GAME_SETTINGS'], 's0'); A.beqz('t0', '.city_bad_hero'); A.nop()
    A.la('a0', 'dm_restart_hero'); A.addiu('a1', 't0', 0x8A8)
    A.li('a2', 32); call('dm_restart_copy')
    A.beqz('v0', '.city_bad_hero'); A.nop()
    A.la('a0', 'dm_restart_path_raw'); A.lw_abs('a1', APP_NAME)
    A.li('a2', PATH_CAPACITY); call('dm_restart_copy')
    A.beqz('v0', '.city_bad_path'); A.nop()
    A.move('s2', 'v0'); A.la('s1', 'dm_restart_path_raw')
    A.move('t0', 's1'); A.move('t1', 'zero')
    # Preserve explicit devices (host:, host0:, cdrom0:, mass:, etc.).
    A.label('.restart_device')
    A.lbu('t2', 0, 't0'); A.beqz('t2', '.restart_device_done'); A.nop()
    A.li('t3', ord(':')); A.beq('t2', 't3', '.restart_has_device'); A.nop()
    A.addiu('t0', 't0', 1); A.nop(); A.b('.restart_device'); A.nop()
    A.label('.restart_has_device'); A.li('t1', 1)
    A.label('.restart_device_done')
    A.la('a3', S(''))
    A.bnez('t1', '.restart_prefix_ready'); A.nop()
    A.lw_abs('t0', BOOT_MODE); A.la('a3', S('host0:'))
    A.beqz('t0', '.restart_prefix_ready'); A.nop()
    A.la('a3', S('cdrom0:'))
    A.label('.restart_prefix_ready')
    A.la('a0', 'dm_restart_path'); A.li('a1', PATH_CAPACITY)
    A.la('a2', S('%s%s')); A.move('t0', 's1'); call(G['snprintf'])
    A.sltiu('t0', 'v0', PATH_CAPACITY); A.beqz('t0', '.city_bad_path'); A.nop()
    A.move('s2', 'v0')
    # Disc boot names require an ISO9660 version suffix. Host paths do not.
    A.la('t0', 'dm_restart_path'); A.la('t1', S('cdrom0:'))
    A.label('.restart_disc_prefix')
    A.lbu('t2', 0, 't1'); A.beqz('t2', '.restart_disc_name'); A.nop()
    A.lbu('t3', 0, 't0'); A.ori('t3', 't3', 0x20)
    A.bne('t2', 't3', '.restart_path_ready'); A.nop()
    A.addiu('t0', 't0', 1); A.addiu('t1', 't1', 1)
    A.b('.restart_disc_prefix'); A.nop()
    A.label('.restart_disc_name')
    A.la('t0', 'dm_restart_path'); A.addu('t0', 't0', 's2')
    A.lbu('t1', -2, 't0'); A.li('t2', ord(';'))
    A.bne('t1', 't2', '.restart_append_version'); A.nop()
    A.lbu('t1', -1, 't0'); A.li('t2', ord('1'))
    A.beq('t1', 't2', '.restart_path_ready'); A.nop()
    A.label('.restart_append_version')
    A.sltiu('t1', 's2', PATH_CAPACITY - 2); A.beqz('t1', '.city_bad_path'); A.nop()
    A.li('t1', ord(';')); A.sb('t1', 0, 't0'); A.li('t1', ord('1'))
    A.sb('t1', 1, 't0'); A.sb('zero', 2, 't0')
    A.label('.restart_path_ready')
    A.lw_abs('t0', KERNEL_ARGS); A.beqz('t0', '.city_boot_not_ready'); A.nop()
    A.lw_abs('t0', PACKER); A.bnez('t0', '.restart_audio_ready'); A.nop()
    A.lw_abs('t0', SOUND_SLOTS); A.beqz('t0', '.city_boot_not_ready'); A.nop()
    A.label('.restart_audio_ready')
    A.la('a0', 'dm_restart_path'); A.li('a1', 1); A.move('a2', 'zero'); call(OPEN)
    A.bltz('v0', '.city_bad_path'); A.nop()
    A.move('a0', 'v0'); call(CLOSE)
    A.bltz('v0', '.city_bad_path'); A.nop()
    A.li('v0', 1); f.ret()
    error('Wait for hero change', '.city_hero_busy'); f.ret()
    error('Level unavailable', '.city_bad_scene'); f.ret()
    error('Hero unavailable', '.city_bad_hero'); f.ret()
    error('Boot executable unavailable', '.city_bad_path'); f.ret()
    error('Restart not ready', '.city_boot_not_ready')
    f.end()

    f = A.func('h_city_restart')
    call('dm_city_restart_prepare')
    A.beqz('v0', f.epi); A.nop()
    call('dm_hide')
    A.sw_abs('zero', 'dm_replay_valid')
    for address, arguments in CLEANUP:
        for index, value in enumerate(arguments): A.li('a%d' % index, value)
        call(address)
    A.la('a0', 'dm_restart_path'); A.li('a1', 5); A.la('a2', 'dm_restart_argv')
    call(LOAD_EXEC)
    # Successful LoadExec never returns. Exit instead of resuming a runtime
    # whose sound, rendering and input handlers have already been dismantled.
    A.la('a0', S('City restart failed: LoadExecPS2 returned\n')); call(KPRINTF)
    A.li('a0', 1); call(EXIT)
    A.label('.restart_halt')
    for _ in range(5): A.nop()
    A.b('.restart_halt'); A.nop()
    f.end()

    f = A.func('r_city_restart_status')
    A.sb('zero', 0, 'a1'); A.lw_abs('a3', 'dm_city_restart_error')
    A.beqz('a3', f.epi); A.nop()
    A.move('a0', 'a1'); A.li('a1', 64); A.la('a2', S('%s')); call(G['snprintf'])
    f.end()


def emit_menus(A, S, C):
    pass


def emit_data(A, S, C):
    A.align(4); A.label('dm_restart_argv')
    for label in (S('skip_to_loading'), S('scene'), 'dm_restart_scene', S('hero'), 'dm_restart_hero'):
        A.word(Ref(label))
    A.word(0)


def emit_bss(A, C):
    A.align(4); A.label('dm_city_restart_error'); A.word(0)
    for label in ('dm_restart_path_raw', 'dm_restart_path'):
        A.label(label); A.space(PATH_CAPACITY)
    for label in ('dm_restart_scene', 'dm_restart_hero'):
        A.label(label); A.space(32)
