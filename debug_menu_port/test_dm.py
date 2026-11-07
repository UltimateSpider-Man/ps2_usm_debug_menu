"""End-to-end test of the injected debug menu inside the interpreter.

usage: test_dm.py <SLES_536.72 (original or patched)>
With the original ELF the freshly built menu is loaded at its low-RAM address; with the
patched ELF the image is loaded exactly like the PS2 loader does it and the
hook sites are checked as well.
"""
import struct, sys
from emu import Mem, CPU, f2b, b2f, s32, c_format
import dm_build as D

G = D.G
A, blob = D.build()
END = A.labels['dm_end']

mem = Mem()
img = open(sys.argv[1], 'rb').read()
phoff, = struct.unpack_from('<I', img, 0x1C)
phnum, = struct.unpack_from('<H', img, 0x2C)
for i in range(phnum):
    # copy filesz, zero-fill to memsz
    ptype, poff, pva, ppa, pfs, pms, pfl, pal = struct.unpack_from('<8I', img, phoff + 32 * i)
    assert ptype == 1
    mem.write(pva, img[poff:poff + pfs] + bytes(pms - pfs))
    print('loaded segment %08x filesz %x memsz %x' % (pva, pfs, pms))
if phnum == 1:
    mem.write(D.BASE, blob)
else:
    assert mem.read(D.BASE, len(blob)) == blob, 'loaded image differs from built blob'
    # the patched call sites must now target the hooks
    for site, hook in ((0x311DAC, 'hook_tick'), (0x295B78, 'hook_render'), (0x37E09C, 'hook_pause'),
                       (0x381254, 'hook_map'), (D.dm_slf.CALL_SITE, 'hook_slf_call')):
        assert mem.u32(site) == 0x0C000000 | (A.labels[hook] >> 2), hex(site)
mem.write(0x01E00000, bytes(0x100000))   # stack area

cpu = CPU(mem, D.BASE, END)
log = []

# ---------------------------------------------------------------- fake game objects
INPUT, FONT, GAME, OSD, WORLD, TERRAIN, REGARR = 0x01000000, 0x01001000, 0x01002000, 0x01003000, 0x01010000, 0x01011000, 0x01012000
mem.write(INPUT, bytes(0x100)); mem.w32(G['input_mgr_instance'], INPUT); mem.w32(INPUT + 4, 0x01000800)
mem.w32(G['nglSysFont'], FONT)
mem.write(GAME, bytes(0x400)); mem.w32(G['g_game_ptr'], GAME)
mem.write(OSD, bytes(0x500)); mem.w32(G['os_dev_instance'], OSD)
mem.w32(OSD + D.OSD_INTS + 4 * D.INT_FRAME_LOCK, 60)
mem.w32(OSD + D.OSD_INTS + 4 * D.INT_GOD_MODE, 0)
# debug render names: real strings from the final's static initializer order
names = ['CAPSULE_HISTORY', 'LIGHTS', 'BOX_TRIGGERS', 'WATER_EXCLUSION_TRIGGERS', 'POINT_TRIGGERS']
names += ['RENDER_OPTION_%02d' % i for i in range(len(names), D.NUM_DEBUG_RENDER)]
strbase = 0x01020000
for i, n in enumerate(names):
    mem.write(strbase + 0x40 * i, n.encode() + b'\0')
    mem.w32(G['debug_render_names'] + 16 * i + 8, strbase + 0x40 * i)
# regions
regions = [('Midtown_01', 0x4000 | 1, 7, 3, (100.0, 2.0, -50.0)),
           ('Chelsea_02', 0x4000, 8, 1, (10.0, 0.0, 5.0)),
           ('hidden_int', 0, 9, 2, (0.0, 0.0, 0.0)),
           ('Bronx_04', 0x4000, 10, 4, (-300.0, 12.0, 77.5))]
mem.write(WORLD, bytes(0x400)); mem.w32(G['g_world_ptr'], WORLD); mem.w32(WORLD + D.WORLD_TERRAIN, TERRAIN)
mem.write(TERRAIN, bytes(0x100)); mem.w32(TERRAIN + D.TERRAIN_REGIONS, REGARR); mem.w32(TERRAIN + D.TERRAIN_NUM_REGIONS, len(regions))
for i, (nm, flags, did, vc, pos) in enumerate(regions):
    rb = 0x01030000 + 0x400 * i
    mash = rb + 0x300
    mem.write(rb, bytes(0x400))
    mem.write(mash, nm.encode() + b'\0')
    mem.w32(rb + D.REGION_MASH, mash)
    mem.w32(rb + D.REGION_FLAGS, flags)
    mem.w32(rb + D.REGION_DISTRICT, did)
    mem.w32(rb + 0xC4, 0)               # current variant
    mem.w32(rb + D.REGION_VARIANT_COUNT, vc)
    for k, f in enumerate(pos):
        mem.w32(rb + D.REGION_SPAWN + 4 * k, f2b(f))
    mem.w32(REGARR + 4 * i, rb)

pressed = {}
state = dict(scene=0, quads=[], texts=[])


def stub(addr):
    def deco(fn):
        cpu.stubs[addr] = fn
        return fn
    return deco


@stub(G['get_control_state'])
def _(c):
    c.f[0] = f2b(pressed.get(s32(c.r[5]), 0.0))

@stub(G['get_control_delta'])
def _(c):
    log.append(('get_control_delta', s32(c.r[5])))
    c.f[0] = f2b(1.0)

@stub(G['nglGetStringDimensions'])
def _(c):
    s = mem.cstr(c.r[5] & 0xffffffff)
    mem.w32(c.r[6] & 0xffffffff, 10 * len(s))
    mem.w32(c.r[7] & 0xffffffff, 15)

@stub(G['nglListAddString'])
def _(c):
    assert c.r[4] & 0xffffffff == FONT
    state['texts'].append((b2f(c.f[12]), b2f(c.f[13]), b2f(c.f[14]), c.r[6] & 0xffffffff, mem.cstr(c.r[5] & 0xffffffff),
                           b2f(c.f[15]), b2f(c.f[16])))

for nm in ('nglInitQuad', 'nglListAddQuad'):
    cpu.stubs[G[nm]] = lambda c, nm=nm: state['quads'].append((nm,))
cpu.stubs[G['nglSetQuadRect']] = lambda c: state['quads'].append(('rect', b2f(c.f[12]), b2f(c.f[13]), b2f(c.f[14]), b2f(c.f[15])))
cpu.stubs[G['nglSetQuadColor']] = lambda c: state['quads'].append(('color', c.r[5] & 0xffffffff))
cpu.stubs[G['nglSetQuadZ']] = lambda c: state['quads'].append(('z', b2f(c.f[12])))
cpu.stubs[G['nglListEndScene']] = lambda c: log.append(('nglListEndScene',))
cpu.stubs[G['link_system_frame_advance']] = lambda c: log.append(('link_system_frame_advance', round(b2f(c.f[12]), 4)))
cpu.stubs[G['igo_zoom_map_on_select']] = lambda c: log.append(('map_open',))

@stub(G['enable_physics'])
def _(c):
    assert c.r[4] & 0xffffffff == GAME
    mem.w32(GAME + D.GAME_STOP_PHYSICS, 0 if (c.r[5] & 0xffffffff) else 1)
    log.append(('enable_physics', c.r[5] & 0xffffffff))

@stub(G['snprintf'])
def _(c):
    fmt = mem.cstr(c.r[6] & 0xffffffff)
    ints = [c.r[7], c.r[8], c.r[9], c.r[10], c.r[11]]
    s = c_format(fmt, ints, mem)
    n = c.r[5] & 0xffffffff
    assert len(s) < n, 'snprintf overflow %r (n=%d)' % (s, n)
    mem.write(c.r[4] & 0xffffffff, s.encode('latin1') + b'\0')
    c.r[2] = len(s)

@stub(G['strcasecmp'])
def _(c):
    a = mem.cstr(c.r[4] & 0xffffffff).lower(); b = mem.cstr(c.r[5] & 0xffffffff).lower()
    c.r[2] = (0 if a == b else (1 if a > b else (-1 & 0xffffffffffffffff)))

@stub(G['region_get_district_variant'])
def _(c):
    c.r[2] = mem.u32((c.r[4] & 0xffffffff) + 0xC4)

@stub(G['terrain_unlock_district'])
def _(c):
    log.append(('unlock_district', s32(c.r[5])))

@stub(G['terrain_set_district_variant'])
def _(c):
    did, var = s32(c.r[5]), s32(c.r[6])
    log.append(('set_district_variant', did, var, s32(c.r[7])))
    for i, r in enumerate(regions):
        if r[2] == did:
            mem.w32(0x01030000 + 0x400 * i + 0xC4, var)

@stub(G['malor_point'])
def _(c):
    v = c.r[5] & 0xffffffff
    log.append(('malor_point', c.r[4] & 0xffffffff == WORLD, tuple(b2f(mem.u32(v + 4 * k)) for k in range(3)), s32(c.r[6]), s32(c.r[7])))

scene = {'on': 0}
cpu.stubs[G['is_scene_analyzer_enabled']] = lambda c: c.r.__setitem__(2, scene['on'])
def _esa(c):
    scene['on'] = c.r[4] & 1
    log.append(('enable_scene_analyzer', scene['on']))
cpu.stubs[G['enable_scene_analyzer']] = _esa
cpu.stubs[G['set_god_mode']] = lambda c: log.append(('set_god_mode', s32(c.r[4])))

# IGO: tracker (+0x54) and hero health widget (+0xC); hero actor with controller
IGO, TRACKER, WIDGET, HERO, CTRL = 0x01040000, 0x01040400, 0x01040800, 0x01041000, 0x01041800
mem.write(IGO, bytes(0x100)); mem.w32(G['igo_ptr'], IGO)
mem.w32(IGO + D.IGO_TRACKER, TRACKER); mem.w32(IGO + D.IGO_HERO_HEALTH, WIDGET)
mem.write(HERO, bytes(0x100)); mem.write(CTRL, bytes(0x500))
mem.w32(HERO + D.ACTOR_CONTROLLER, CTRL); mem.w32(HERO + D.ENTITY_HANDLE, 0x1234)
mem.w32(WORLD + D.WORLD_HERO0, HERO); mem.w32(WORLD + D.WORLD_NUM_PLAYERS, 1)
packs = {'ultimate_spiderman', 'venom', 'mary_jane', 'green_goblin', 'peter_parker', 'shield_agent'}
hashes = {}

@stub(G['get_the_arrow_target_pos'])
def _(c):
    assert c.r[4] & 0xffffffff == TRACKER
    v = c.r[5] & 0xffffffff
    for k, f in enumerate((1.0, 2.0, 3.0)):
        mem.w32(v + 4 * k, f2b(f))
    c.r[2] = 1

@stub(G['string_hash_init'])
def _(c):
    name = mem.cstr(c.r[6] & 0xffffffff)
    h = (hash(name) & 0x7fffffff) | 1
    hashes[h] = name
    mem.w32(c.r[4] & 0xffffffff, h)

@stub(G['get_pack_file_stats'])
def _(c):
    k = c.r[4] & 0xffffffff
    assert mem.u32(k + 4) == 0x19 and (c.r[5] | c.r[6] | c.r[7]) == 0
    c.r[2] = 1 if hashes.get(mem.u32(k)) in packs else 0

@stub(G['remove_player'])
def _(c):
    assert c.r[4] & 0xffffffff == WORLD
    log.append(('remove_player', s32(c.r[5])))
    mem.w32(WORLD + D.WORLD_NUM_PLAYERS, 0); mem.w32(WORLD + D.WORLD_HERO0, 0)

@stub(G['add_player'])
def _(c):
    assert c.r[4] & 0xffffffff == WORLD and mem.u32(WORLD + D.WORLD_NUM_PLAYERS) == 0
    name = mem.cstr(mem.u32((c.r[5] & 0xffffffff) + 8))
    log.append(('add_player', name))
    mem.w32(WORLD + D.WORLD_NUM_PLAYERS, 1); mem.w32(WORLD + D.WORLD_HERO0, HERO)
    mem.w32(CTRL + D.CONTROLLER_HERO_TYPE, 2 if name == 'venom' else 1)

@stub(G['mstring_ctor'])
def _(c):
    mem.w32((c.r[4] & 0xffffffff) + 8, c.r[5] & 0xffffffff)
cpu.stubs[G['mstring_finalize']] = lambda c: None
cpu.stubs[G['mcontainer_finalize']] = lambda c: None
cpu.stubs[G['enable_marky_cam']] = lambda c: log.append(('marky', c.r[5] & 1, c.r[6] & 1, b2f(c.f[12]), b2f(c.f[13])))
cpu.stubs[G['health_set_type']] = lambda c: log.append(('SetType', c.r[4] & 0xffffffff == WIDGET, s32(c.r[5]), c.r[6] & 0xffffffff))
cpu.stubs[G['health_set_shown']] = lambda c: log.append(('SetShown', c.r[4] & 0xffffffff == WIDGET, c.r[5] & 1))
cpu.stubs[G['enable_vibration']] = lambda c: log.append(('enable_vibration',))
cpu.stubs[G['disable_vibration']] = lambda c: log.append(('disable_vibration',))
cpu.stubs[D.dm_missions.NATIVE['partition']] = lambda c: c.r.__setitem__(2, 0)

import test_font
test_font.install_stubs(globals())

# ---------------------------------------------------------------- frame driver
def frame(buttons=(), axes=None, dt=1 / 50.0, show=False):
    pressed.clear()
    for b in buttons:
        pressed[b] = 1.0
    if axes:
        pressed.update(axes)
    state['texts'].clear(); state['quads'].clear()
    cpu.call(A.labels['hook_tick'], fargs=(dt,))
    cpu.call(A.labels['hook_render'])
    if show:
        dump()

def tap(b, show=False):
    frame((D.DMENU_TOGGLE, D.DMENU_FOCUS_TOGGLE) if b == D.DMENU_TOGGLE else (b,))
    frame((), show=show)

def dump():
    print('-' * 60)
    for q in state['quads']:
        if q[0] in ('rect', 'color'):
            print('   quad', q)
    for t in state['texts']:
        print('   (%5.1f,%5.1f) %08x  %s' % (t[0], t[1], t[3], t[4]))

def flag(i): return mem.u32(OSD + D.OSD_FLAGS + 4 * i)
def var(name): return mem.u32(A.labels[name])

def menu_title():
    m = var('dm_active_menu')
    return mem.cstr(mem.u32(m)) if m else None

def goto(name):
    """move highlight down until the given entry is highlighted."""
    for _ in range(400):
        m = var('dm_active_menu')
        assert m, 'cannot navigate to %r: debug menu is closed' % name
        h = mem.u32(m + D.M_HIGHLIGHT)
        if h and mem.cstr(mem.u32(h + D.E_NAME)) == name:
            return
        tap(D.DMENU_DOWN)
    raise AssertionError('entry %s not found' % name)

# ---------------------------------------------------------------- scenario
frame(show=True)
assert var('dm_active_menu') == 0 and not state['texts']
assert ('link_system_frame_advance', 0.02) in log, log

tap(D.DMENU_TOGGLE, show=True)                    # Start + Select opens the menu
assert menu_title() == 'Debug Menu'
assert var('dm_has_focus') == 1 and mem.u32(GAME + D.GAME_STOP_PHYSICS) == 1, 'physics should be stopped'
assert mem.u32(A.labels['dm_debug_render'] + D.M_COUNT) == D.NUM_DEBUG_RENDER + 1
assert mem.u32(A.labels['dm_static_pool_desc'] + 4) < D.N_STATIC, 'static menu pool exhausted'
titles = [t[4] for t in state['texts']]
assert titles == ['Debug Menu', 'Warp: >', 'Game: >', 'Missions: >', 'Replay: >', 'Debug Render: >',
                  'District variants: >', 'AI: >', 'Memory: >', 'Entity Variants: >', 'Level Select: >',
                  'Script: >', 'Progression: >', 'Camera: Chase'], titles

# pause / map hooks while the menu has focus
log.clear()
cpu.call(A.labels['hook_pause'], args=(INPUT, 0x36, -1))
assert b2f(cpu.f[0]) == 0.0 and not log, 'pause must be blocked'
cpu.call(A.labels['hook_map'], args=(0x12345678,))
assert not log, 'map must be blocked'

# Game menu -> Show FPS
goto('Game: >' if False else 'Game')
tap(D.DMENU_SELECT, show=True)
assert menu_title() == 'Game'
names_in_game = [t[4] for t in state['texts']]
print(names_in_game)
assert names_in_game[1:3] == ['Devopt Ints: >', 'Devopt Flags: >'], names_in_game
assert 'Script Variables: >' not in names_in_game, names_in_game
goto('Show FPS')
tap(D.DMENU_SELECT)
assert flag(D.FLAG_SHOW_FPS) == 1, 'SHOW_FPS not set'
assert var('dm_active_menu') == 0 and mem.u32(GAME + D.GAME_STOP_PHYSICS) == 0, 'menu should close and physics resume'

# reopen, back out to root with triangle/circle, check map hook passes when closed
tap(D.DMENU_TOGGLE)
assert menu_title() == 'Debug Menu', menu_title()
tap(D.DMENU_TOGGLE)
assert var('dm_active_menu') == 0
frame(())
log.clear()
cpu.call(A.labels['hook_map'], args=(0x12345678,))
assert log == [('map_open',)], log
log.clear()
cpu.call(A.labels['hook_pause'], args=(INPUT, 0x36, -1))
assert log == [('get_control_delta', 0x36)] and b2f(cpu.f[0]) == 1.0

# Warp
tap(D.DMENU_TOGGLE)
goto('Warp')
tap(D.DMENU_SELECT, show=True)
assert menu_title() == 'Warp'
wl = [t[4] for t in state['texts']]
assert wl == ['Warp', '--WARP TO POI--', 'Bronx_04', 'Chelsea_02', 'Midtown_01'], wl   # sorted, filtered by 0x4000
goto('Midtown_01')
log.clear()
tap(D.DMENU_SELECT)
print(log)
assert ('unlock_district', 7) in log
assert ('malor_point', True, (100.0, 2.0, -50.0), 0, 0) in log
assert var('dm_active_menu') == 0

# District variants: int entries with live render, change with RIGHT
tap(D.DMENU_TOGGLE)
goto('District variants')
tap(D.DMENU_SELECT, show=True)
dl = [t[4] for t in state['texts']]
assert dl == ['District variants', 'Bronx_04: 0 [0, 3]', 'hidden_int: 0 [0, 1]', 'Midtown_01: 0 [0, 2]'], dl
goto('Bronx_04')
log.clear()
tap(D.DMENU_RIGHT, show=True)
assert ('set_district_variant', 10, 1, 1) in log, log
assert 'Bronx_04: 1 [0, 3]' in [t[4] for t in state['texts']]
tap(D.DMENU_LEFT); tap(D.DMENU_LEFT)            # clamps at 0
assert mem.u32(0x01030000 + 0x400 * 3 + 0xC4) == 0

# back to root, camera
tap(D.DMENU_BACK)
assert menu_title() == 'Debug Menu'
goto('Camera')
tap(D.DMENU_RIGHT, show=True)
assert mem.u32(GAME + D.GAME_USER_CAMERA) == 1
tap(D.DMENU_RIGHT)
assert mem.u32(GAME + D.GAME_USER_CAMERA) == 0 and scene['on'] == 1
tap(D.DMENU_RIGHT)                                  # clamped at 2
tap(D.DMENU_LEFT); tap(D.DMENU_LEFT, show=True)
assert scene['on'] == 0 and mem.u32(GAME + D.GAME_USER_CAMERA) == 0

# Devopt flags paging + toggle
goto('Game')
tap(D.DMENU_SELECT)
goto('Devopt Flags')
tap(D.DMENU_SELECT, show=True)
assert len(state['texts']) == 1 + 21
tap(D.DMENU_PGDN, show=True)
tap(D.DMENU_PGDN)
h = mem.u32(var('dm_active_menu') + D.M_HIGHLIGHT)
print('after 2x pgdn:', mem.cstr(mem.u32(h)))
goto('GOD_MODE' if False else 'SHOW_STATS')
tap(D.DMENU_SELECT)
assert flag(18) == 1, 'SHOW_STATS flag'
tap(D.DMENU_BACK); tap(D.DMENU_BACK)
assert menu_title() == 'Debug Menu'

# Devopt ints: FRAME_LOCK right
goto('Game'); tap(D.DMENU_SELECT); goto('Devopt Ints'); tap(D.DMENU_SELECT)
goto('FRAME_LOCK')
tap(D.DMENU_RIGHT, show=False)
assert mem.u32(OSD + D.OSD_INTS + 4 * 13) == 61
tap(D.DMENU_BACK); tap(D.DMENU_BACK)

# Debug render
goto('Debug Render'); tap(D.DMENU_SELECT, show=True)
goto('LIGHTS')
mem.w32(G['debug_render_max'] + 4, 3)
tap(D.DMENU_RIGHT, show=True)
assert mem.u32(G['debug_render_items'] + 4) == 1
tap(D.DMENU_BACK)

# focus release keeps menu visible, START regrabs
tap(D.DMENU_FOCUS_TOGGLE, show=True)
assert var('dm_has_focus') == 0 and var('dm_active_menu') != 0
assert mem.u32(GAME + D.GAME_STOP_PHYSICS) == 0
assert state['quads'][2] == ('color', D.COL_BG_NOFOCUS), state['quads']
tap(D.DMENU_FOCUS_TOGGLE)
assert var('dm_has_focus') == 1 and mem.u32(GAME + D.GAME_STOP_PHYSICS) == 1

# key repeat: holding DOWN for 1s at 50fps
m = var('dm_active_menu')
before = mem.u32(m + D.M_HIGHLIGHT)
moves = 0
last = before
for i in range(50):
    frame((D.DMENU_DOWN,))
    h = mem.u32(m + D.M_HIGHLIGHT)
    if h != last:
        moves += 1; last = h
frame(())
print('moves while holding 1s:', moves)
assert 10 <= moves <= 20, moves

# god mode + slow motion close the menu and call the game
goto('Game'); tap(D.DMENU_SELECT); goto('God Mode')
log.clear(); tap(D.DMENU_RIGHT)
assert ('set_god_mode', 1) in log and var('dm_active_menu') == 0
tap(D.DMENU_TOGGLE); goto('Game'); tap(D.DMENU_SELECT); goto('Slow Motion Enabled')
tap(D.DMENU_SELECT)
assert mem.u32(OSD + D.OSD_INTS + 4 * 13) == 120 and var('dm_old_frame_lock') == 61
tap(D.DMENU_TOGGLE); goto('Game'); tap(D.DMENU_SELECT); goto('Slow Motion Enabled'); tap(D.DMENU_SELECT)
assert mem.u32(OSD + D.OSD_INTS + 4 * 13) == 61
# POI warp
tap(D.DMENU_TOGGLE); goto('Warp'); tap(D.DMENU_SELECT); goto('--WARP TO POI--')
log.clear(); tap(D.DMENU_SELECT)
assert ('malor_point', True, (1.0, 2.0, 3.0), 0, 0) in log and var('dm_active_menu') == 0, log

# Hero select: only heroes with packs, then the 3-step swap
CURRENT_HERO_SETTINGS = 0x01060000
mem.write(CURRENT_HERO_SETTINGS, bytes(0xA00))
mem.w32(GAME + D.GAME_SETTINGS, CURRENT_HERO_SETTINGS)
mem.write(CURRENT_HERO_SETTINGS + 0x8A8, b'ultimate_spiderman\0')
tap(D.DMENU_TOGGLE); goto('Level Select'); tap(D.DMENU_SELECT)
goto('Hero Select'); tap(D.DMENU_SELECT, show=True)
hl = [t[4] for t in state['texts']]
assert hl == ['Hero Select', 'ultimate_spiderman: True', 'venom: False', 'shield_agent: False',
              'mary_jane: False', 'green_goblin: False', 'peter_parker: False'], hl
goto('venom')
log.clear()
frame((D.DMENU_SELECT,))
for i in range(8):
    frame(())
print(log)
seq = [e for e in log if e[0] in ('remove_player', 'add_player', 'marky', 'SetType', 'SetShown')]
assert seq == [('remove_player', 0), ('marky', 1, 1, -1000.0, 0.0), ('add_player', 'venom'), ('marky', 0, 1, -1000.0, 0.0),
               ('SetType', True, 4, 0x1234), ('SetShown', True, 1)], seq
assert var('dm_hero_status') == 0 and var('dm_active_menu') == 0
# frame spacing: remove on the select frame, add 3 frames later, widget 3 frames after that
idx = [i for i, e in enumerate(log) if e[0] in ('remove_player', 'add_player', 'SetType')]
ticks = [sum(1 for e in log[:i] if e[0] == 'link_system_frame_advance') for i in idx]
assert ticks == [0, 3, 6], ticks
# Saved-game editor: typed writes, full list, float formatting and clamps.
SETTINGS_OBJECT = 0x01060000
mem.write(SETTINGS_OBJECT, bytes(0xA00))
mem.w32(GAME + D.GAME_SETTINGS, SETTINGS_OBJECT)
mem.w32(SETTINGS_OBJECT + 0x75C, f2b(0.9))
mem.w32(SETTINGS_OBJECT + 0x7B8, f2b(100.0))
tap(D.DMENU_TOGGLE); goto('Game'); tap(D.DMENU_SELECT)
goto('Saved Game Settings'); tap(D.DMENU_SELECT)
assert menu_title() == 'Saved Game Settings'
assert mem.u32(var('dm_active_menu') + D.M_COUNT) == 97
goto('HERO_POINTS'); tap(D.DMENU_RIGHT)
assert mem.u32(SETTINGS_OBJECT + 0x720) == 1
assert mem.u32(SETTINGS_OBJECT + 0x724) == 0
goto('ENABLE_WEB_YANK'); tap(D.DMENU_SELECT)
assert mem.u32(SETTINGS_OBJECT + 0x78C) == 1
goto('OPT_LEVELS_GAME'); tap(D.DMENU_RIGHT); tap(D.DMENU_RIGHT)
assert b2f(mem.u32(SETTINGS_OBJECT + 0x75C)) == 1.0
goto('HERO_HEALTH'); tap(D.DMENU_RIGHT)
assert abs(b2f(mem.u32(SETTINGS_OBJECT + 0x7B8)) - 100.1) < 0.0001
assert any(t[4] == 'HERO_HEALTH: 100.10' for t in state['texts'])
goto('CITY_EVENTS_COMPLETED_TOT_MAX'); tap(D.DMENU_RIGHT)
assert mem.u32(SETTINGS_OBJECT + 0x8A0) == 1
tap(D.DMENU_BACK)
assert menu_title() == 'Game'
mem.w32(GAME + D.GAME_SETTINGS, 0)
goto('Saved Game Settings'); tap(D.DMENU_SELECT)
assert mem.u32(var('dm_active_menu') + D.M_COUNT) == 0
mem.w32(GAME + D.GAME_SETTINGS, SETTINGS_OBJECT)
tap(D.DMENU_TOGGLE)

from test_game_extra import run as run_game_extra
run_game_extra(globals())
from test_missions import run as run_missions
run_missions(globals())
from test_mission_heroes import run as run_mission_heroes
run_mission_heroes()
from test_entities import run as run_entities
run_entities(globals())
from test_game_actions import run as run_game_actions
run_game_actions(globals())
from test_script_commands import run as run_script_commands
run_script_commands(globals())
from test_memory import run as run_memory
run_memory()
from test_ai import run as run_ai
run_ai()
from test_controls import run as run_controls
run_controls()
from test_start_select import run as run_start_select
run_start_select()
from test_hero_marker import run as run_hero_marker
run_hero_marker()
from test_slf import run as run_slf
run_slf()
from test_city_restart import run as run_city_restart
run_city_restart()

print('steps executed:', cpu.steps)
print('ALL TESTS PASSED')
