"""Behavioral interpreter scenarios for resident levels and authored missions.

Called by test_dm after its base menu scenarios, with run(globals()). Native
resource-loading and mission execution are narrow fakes; injected traversal,
pagination, name ownership, bounds, focus and dispatch execute as EE code.
"""
import struct
from dm_missions import NATIVE, PAGE_SIZE


def run(ctx):
    mem, cpu, D, A, G = (ctx[k] for k in ('mem', 'cpu', 'D', 'A', 'G'))
    tap, goto, var, title, log = (ctx[k] for k in ('tap', 'goto', 'var', 'menu_title', 'log'))
    packs, hashes, CTRL = (ctx[k] for k in ('packs', 'hashes', 'CTRL'))
    original_scene = mem.read(G['scene_name'], 64)
    original_manager = mem.u32(NATIVE['manager_ptr'])
    original_hero_type = mem.u32(CTRL + D.CONTROLLER_HERO_TYPE)
    mem.write(G['scene_name'], b'city\0')
    mem.w32(CTRL + D.CONTROLLER_HERO_TYPE, 2)

    def root():
        if var('dm_active_menu'):
            tap(D.DMENU_TOGGLE)
        tap(D.DMENU_TOGGLE)
        assert title() == 'Debug Menu'

    def open_path(*names):
        root()
        for name in names:
            goto(name); tap(D.DMENU_SELECT)

    def names():
        result = []
        entry = mem.u32(var('dm_active_menu') + D.M_FIRST)
        while entry:
            result.append(mem.cstr(mem.u32(entry + D.E_NAME)))
            entry = mem.u32(entry + D.E_NEXT)
        return result

    partition, slot_array, slot, directory, levels = (0x01100000 + i * 0x1000 for i in range(5))
    mem.write(partition, bytes(0x6000))
    mem.w32(partition + 8, slot_array); mem.w32(slot_array, slot)
    scene_names = ('CITY_ARENA', 'stadium', 'absent_level')
    for i, name in enumerate(scene_names):
        mem.write(levels + i * 0x90, name.encode() + b'\0')
    packs.update(('CITY_ARENA', 'stadium', 'pk_story_v01', 'pk_story_s01'))

    def partition_stub(c):
        assert c.r[4] == 0
        c.r[2] = partition

    def directory_stub(c):
        assert c.r[4] == slot
        c.r[2] = directory

    def resource_stub(c):
        assert c.r[4] == directory
        key = c.r[5] & 0xffffffff
        assert hashes[mem.u32(key)] == 'level' and mem.u32(key + 4) == 9
        mem.w32(c.r[6] & 0xffffffff, len(scene_names) * 0x90)
        c.r[2] = levels

    def load_level(c):
        assert c.r[4] == ctx['GAME']
        log.append(('catalog_load_level', mem.cstr(mem.u32((c.r[5] & 0xffffffff) + 8))))

    for key, stub in (('partition', partition_stub), ('directory', directory_stub), ('resource', resource_stub)):
        cpu.stubs[NATIVE[key]] = stub
    cpu.stubs[G['load_new_level']] = load_level
    open_path('Level Select')
    assert title() == 'Level Select' and names() == ['Hero Select', 'city', 'stadium', '-- REBOOT --'], names()
    # Opening the shared-pool hero child must not invalidate this parent.
    goto('Hero Select'); tap(D.DMENU_SELECT); tap(D.DMENU_BACK)
    assert names() == ['Hero Select', 'city', 'stadium', '-- REBOOT --']
    # The city alias must still launch its original resource after streaming.
    mem.write(levels, b'reused_city_buffer\0')
    goto('city')
    city_entry = mem.u32(var('dm_active_menu') + D.M_HIGHLIGHT)
    assert mem.cstr(mem.u32(city_entry + D.E_ID)) == 'CITY_ARENA'
    assert mem.u32(city_entry + D.E_HANDLER) == A.labels['h_city_restart']
    mem.write(levels, b'CITY_ARENA\0')
    open_path('Level Select')
    # The menu owns names, including the launch key, after resource memory changes.
    mem.write(levels + 0x90, b'reused_buffer\0')
    goto('stadium'); log.clear(); tap(D.DMENU_SELECT)
    assert ('catalog_load_level', 'stadium') in log and var('dm_active_menu') == 0
    mem.write(levels + 0x90, b'stadium\0')
    open_path('Level Select')
    goto('-- REBOOT --'); log.clear(); tap(D.DMENU_SELECT)
    assert title() == 'Level Select' and not any(e[0] == 'catalog_load_level' for e in log)
    mem.w32(A.labels['dm_level_page'], 0)

    manager, table, conditions, instances, mission_names = (0x01110000, 0x01111000, 0x01112000, 0x01120000, 0x01130000)
    mem.write(manager, bytes(0x1000)); mem.write(table, bytes(0x1000))
    mem.write(conditions, bytes(0x1000)); mem.write(instances, bytes(0x10000))
    mem.write(mission_names, bytes(0x1000))
    mem.w32(NATIVE['manager_ptr'], manager)
    mem.w32(manager + 0x14, table); mem.w32(manager + 0x38, 0)
    mem.w32(table + 0x38, conditions); mem.write(table + 0x3C, struct.pack('<H', 3))
    for i, (name, hero_flags) in enumerate((('story_v01', 0x4000), ('story_s01', 0x8000), ('missing_script', 0x4000))):
        name_ptr = mission_names + i * 64
        mem.write(name_ptr, name.encode() + b'\0')
        cond = conditions + i * 0x34
        mem.w32(cond + 0x18, name_ptr); mem.w32(cond + 0x28, hero_flags)
        mem.w32(cond + 8, instances); mem.write(cond + 12, struct.pack('<H', 2))
    mem.write(mission_names + 0x100, b'variant_a\0')
    mem.w32(instances + 0x18, mission_names + 0x100); mem.w32(instances + 0x54, 8)

    def applies(c):
        flags = mem.u32((c.r[4] & 0xffffffff) + 0x28)
        hero = mem.u32(CTRL + D.CONTROLLER_HERO_TYPE)
        c.r[2] = bool(flags & {1: 0x8000, 2: 0x4000, 3: 0x10000}.get(hero, 0))

    def force(c):
        assert c.r[4] == manager
        log.append(('force_mission', c.r[5] & 0xffffffff,
                    mem.cstr(c.r[6] & 0xffffffff), c.r[7] & 0xffffffff,
                    mem.cstr(c.r[8] & 0xffffffff) if c.r[8] else None))

    cpu.stubs[NATIVE['applies_to_hero']] = applies
    cpu.stubs[NATIVE['force_mission']] = force
    cpu.stubs[NATIVE['unload_mission']] = lambda c: log.append(('unload_mission', c.r[4] == manager))
    mem.w32(A.labels['dm_replay_valid'], 0)
    open_path('Replay')
    assert names() == ['Start'], names()
    start = mem.u32(var('dm_active_menu') + D.M_FIRST)
    assert mem.u32(start + D.E_TYPE) == D.T_ACTION
    assert mem.u32(start + D.E_SUBMENU) == 0
    assert [t[4] for t in ctx['state']['texts']] == ['Replay', 'Start']
    log.clear(); tap(D.DMENU_SELECT)
    assert title() == 'Replay' and not any(e[0] == 'force_mission' for e in log)
    open_path('Missions')
    assert title() == 'Missions' and names() == ['UNLOAD CURRENT MISSION', 'story_v01', 'story_v01'], names()
    goto('story_v01')
    assert any(t[4] == 'story_v01 (variant_a)' for t in ctx['state']['texts'])
    # Free/reuse the authored strings while the menu is visible. Owned copies
    # must still dispatch the exact original script/data tuple.
    mem.write(mission_names, b'freed_name\0'); mem.write(mission_names + 0x100, b'freed_data\0')
    log.clear(); tap(D.DMENU_SELECT)
    expected = ('force_mission', 0, 'story_v01', 0, 'variant_a')
    assert expected in log and var('dm_active_menu') == 0, log
    open_path('Replay'); goto('Start')
    log.clear(); tap(D.DMENU_SELECT)
    assert expected in log and var('dm_active_menu') == 0
    # Replay is scoped to the same scene and hero, and survives rebuilding other menus.
    mem.write(G['scene_name'], b'stadium\0')
    open_path('Replay'); goto('Start'); log.clear(); tap(D.DMENU_SELECT)
    assert not any(e[0] == 'force_mission' for e in log) and title() == 'Replay'
    assert [t[4] for t in ctx['state']['texts']] == ['Replay', 'Start']
    mem.write(G['scene_name'], b'city\0'); mem.w32(CTRL + D.CONTROLLER_HERO_TYPE, 1)
    log.clear(); tap(D.DMENU_SELECT)
    assert not any(e[0] == 'force_mission' for e in log)
    mem.w32(CTRL + D.CONTROLLER_HERO_TYPE, 2)
    open_path('Missions'); goto('UNLOAD CURRENT MISSION'); log.clear(); tap(D.DMENU_SELECT)
    assert ('unload_mission', True) in log and var('dm_active_menu') == 0

    # Pagination crosses instance boundaries without losing or repeating IDs.
    mem.write(mission_names, b'story_v01\0'); mem.write(mission_names + 0x100, b'variant_a\0')
    mem.write(conditions + 12, struct.pack('<H', PAGE_SIZE + 3))
    open_path('Missions')
    assert names() == ['UNLOAD CURRENT MISSION'] + ['story_v01'] * PAGE_SIZE + ['Next page']
    goto('Next page'); tap(D.DMENU_SELECT)
    assert names() == ['UNLOAD CURRENT MISSION'] + ['story_v01'] * 3 + ['Previous page']
    goto('story_v01'); log.clear(); tap(D.DMENU_SELECT)
    assert ('force_mission', 0, 'story_v01', PAGE_SIZE, None) in log

    # District-table entries carry the region's retail district ID (offset C0),
    # not their array position or the beta region offset.
    mem.w32(A.labels['dm_mission_page'], 0)
    district_table, district_region, district_condition = 0x01140000, 0x01141000, 0x01142000
    mem.write(district_table, bytes(0x3000))
    mem.w32(manager + 0x14, table); mem.w32(manager + 0x18, district_table)
    mem.write(conditions + 12, struct.pack('<H', 2))
    mem.w32(manager + 0x38, 1)
    mem.w32(district_table + 0x44, district_region); mem.w32(district_region + 0xC0, 7)
    mem.write(district_region + 0xD0, b'IG\0'); mem.w32(district_region + D.REGION_MASH, district_region + 0xD0)
    mem.w32(district_table + 0x38, district_condition)
    mem.write(district_table + 0x3C, struct.pack('<H', 1))
    mem.w32(district_condition + 0x18, mission_names); mem.w32(district_condition + 0x28, 0x4000)
    mem.w32(district_condition + 8, instances + 0x68)
    mem.write(district_condition + 12, struct.pack('<H', 1))
    open_path('Missions')
    parent_names = ['IG', 'UNLOAD CURRENT MISSION', 'story_v01', 'story_v01']
    assert names() == parent_names, names()
    goto('IG'); tap(D.DMENU_SELECT)
    assert title() == 'IG' and names() == ['story_v01']
    tap(D.DMENU_BACK)
    assert title() == 'Missions' and names() == parent_names
    assert any(t[4] == 'story_v01 (variant_a)' for t in ctx['state']['texts'])
    goto('IG'); tap(D.DMENU_SELECT)
    log.clear(); tap(D.DMENU_SELECT)
    assert ('force_mission', 7, 'story_v01', 0, None) in log

    # No accidental reads/calls when runtime objects or resource ranges are absent.
    mem.w32(NATIVE['manager_ptr'], 0)
    open_path('Missions')
    assert names() == ['UNLOAD CURRENT MISSION']
    mem.w32(NATIVE['manager_ptr'], manager); mem.w32(manager + 0x38, 9)
    open_path('Missions')
    assert names() == ['UNLOAD CURRENT MISSION']
    mem.w32(manager + 0x38, 0); mem.w32(manager + 0x14, table)
    mem.w32(table + 0x38, 0x01FFFFF0)
    open_path('Missions')
    assert names() == ['UNLOAD CURRENT MISSION']

    # Level pages retain all available descriptors beyond the bounded pool.
    scene_names = tuple('level%03d' % i for i in range(PAGE_SIZE + 1))
    packs.update(scene_names)
    for i, name in enumerate(scene_names):
        mem.write(levels + i * 0x90, name.encode() + b'\0')
    mem.w32(A.labels['dm_level_page'], 0)
    open_path('Level Select')
    assert names() == ['Hero Select'] + list(scene_names[:PAGE_SIZE]) + ['-- REBOOT --', 'Next page']
    goto('Next page'); tap(D.DMENU_SELECT)
    assert names() == ['Hero Select', 'level064', '-- REBOOT --', 'Previous page'], names()
    goto('level064')
    log.clear(); tap(D.DMENU_SELECT)
    assert ('catalog_load_level', 'level064') in log

    if var('dm_active_menu'):
        tap(D.DMENU_TOGGLE)
    mem.write(G['scene_name'], original_scene)
    mem.w32(NATIVE['manager_ptr'], original_manager)
    mem.w32(CTRL + D.CONTROLLER_HERO_TYPE, original_hero_type)
    mem.w32(A.labels['dm_mission_page'], 0)
    mem.w32(A.labels['dm_level_page'], 0)
    print('LEVEL / MISSION / REPLAY TESTS PASSED')
