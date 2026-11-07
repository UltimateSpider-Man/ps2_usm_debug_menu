"""Video catalog parity using real authored flags and the native hero filter."""
import json
from pathlib import Path
import struct
import dm_build as D
from emu import Mem, CPU, c_format

SPIDEY = [
    'credits (0)',
    *[f'{area}_combat_tour{suffix} (0)' for area in ('downtown', 'midtown', 'queens')
      for suffix in ('', '2', '3', '4')],
    's01_fathers_pride (s01_fathers_pride00)', 's02_workout (s02_workout00)',
    's03_igc1 (0)', 's03_rhino_rampage_enc (s03_rhino_rampage_enc)',
    's04_rhino_beatdown (s04_rhino_beatdown)', 's05_opening_igc (0)',
    's05_sky_chase (s05_sky_chase_inst)', 's06_skyscraper_battle (s06_skyscraper_battle_inst)',
    's07_ending_igc (0)', 's07_gg_vs_spidey (s07_gg_vs_spidey_inst)', 's07_opening_igc (0)',
    's08_class_trip (s08_class_trip00)', 's09_igc1 (0)',
    's10_spidey_vs_sable (s10_spidey_vs_sable00)', 's11_defend_sable (s11_defend_sable00)',
    's13_ending_igc (0)', 's13_final_battle (s13_final_battle00)',
    *[f'uptown_combat_tour{suffix} (0)' for suffix in ('', '2', '3', '4')],
]
VENOM = [
    'credits (0)', 'v01_feeding_time (v01_feeding_time_00)', 'v01_opening_igc (0)',
    'v02_wolverine (v02_wolverine_00)', 'v03_opening_igc (0)',
    'v03_throw_down (v03_throw_down_00)', 'v07_electro_chase (v07_electro_chase00)',
    'v07_opening_igc (0)', 'v08_electro_finale (Electro_finale00)', 'v09_ending_igc (0)',
    'v09_great_escape (v09_great_escape00)', 'v09_opening_igc (0)',
    'v10_Beetle_Battle (v10_beetle_battle00)', 'v12_Venvscar (v12_venvscar00)',
    'vmg_hot_pursuit (vmg_hot_pursuit_00)',
]


def run():
    root = Path(__file__).resolve().parent
    fixture = json.loads((root / 'mission_video_fixture.json').read_text())
    A, blob = D.build(); mem = Mem(); mem.write(D.BASE, blob)
    native = (root.parent / 'source/SLES_536.72').read_bytes()
    address = D.dm_missions.NATIVE['applies_to_hero']
    # Execute the actual shipped current-hero filter, not a permissive fake.
    mem.write(address, native[address - 0x100000 + 0x1000:address - 0x100000 + 0x1000 + 0x98])
    mem.write(0x01000000, bytes(0x80000)); mem.write(0x01E00000, bytes(0x100000))
    cpu = CPU(mem, D.BASE, A.labels['dm_end'])
    native_cpu = CPU(mem, address, address + 0x98)
    def native_filter(c):
        c.r[2] = native_cpu.call(address, args=(c.r[4] & 0xffffffff,))
    cpu.stubs[address] = native_filter
    WORLD, HERO, CTRL, MANAGER, TABLE, CONDS, ENTRY = [0x01000000 + i * 0x1000 for i in range(7)]
    ENTRY = 0x0100F000
    mem.w32(D.G['g_world_ptr'], WORLD); mem.w32(WORLD + D.WORLD_HERO0, HERO)
    mem.w32(HERO + D.ACTOR_CONTROLLER, CTRL)
    mem.w32(D.dm_missions.NATIVE['manager_ptr'], MANAGER); mem.w32(MANAGER + 0x14, TABLE)
    mem.w32(TABLE + 0x38, CONDS); mem.write(TABLE + 0x3C, struct.pack('<H', len(fixture['conditions'])))
    cursor = 0x01010000
    def string(value):
        nonlocal cursor
        address = cursor; cursor += 64; mem.write(address, value.encode() + b'\0'); return address
    for i, row in enumerate(fixture['conditions']):
        c = CONDS + i * 0x34; mem.w32(c + 0x18, string(row['name']))
        mem.w32(c + 0x28, int(row['flags'], 16))
        ins = 0x01030000 + i * 0x100
        mem.w32(c + 8, ins); mem.write(c + 12, struct.pack('<H', len(row['instances'])))
        for j, data in enumerate(row['instances']):
            if data:
                mem.w32(ins + j * 0x68 + 0x18, string(data)); mem.w32(ins + j * 0x68 + 0x54, 8)
    mem.write(D.G['scene_name'], b'CITY_ARENA\0')
    hashes = {}; packs = {p.lower() for p in fixture['packs']}
    def hash_name(c):
        name = mem.cstr(c.r[6] & 0xffffffff); h = len(hashes) + 1
        hashes[h] = name.lower(); mem.w32(c.r[4] & 0xffffffff, h)
    def snprintf(c):
        value = c_format(mem.cstr(c.r[6] & 0xffffffff), list(c.r[7:12]), mem)
        assert len(value) < c.r[5]
        mem.write(c.r[4] & 0xffffffff, value.encode() + b'\0')
    def compare(c):
        a, b = (mem.cstr(c.r[i] & 0xffffffff).lower() for i in (4, 5))
        c.r[2] = ((a > b) - (a < b)) & 0xffffffffffffffff
    cpu.stubs[D.G['string_hash_init']] = hash_name
    cpu.stubs[D.G['get_pack_file_stats']] = lambda c: c.r.__setitem__(2, hashes[mem.u32(c.r[4])] in packs)
    cpu.stubs[D.G['snprintf']] = snprintf; cpu.stubs[D.G['strcasecmp']] = compare
    def catalog(hero):
        mem.w32(CTRL + D.CONTROLLER_HERO_TYPE, hero)
        mem.w32(A.labels['dm_active_menu'], A.labels['dm_root_menu'])
        cpu.call(A.labels['p_missions_catalog'], args=(ENTRY,))
        current = mem.u32(A.labels['dm_missions_menu'] + D.M_FIRST); rows = []
        while current:
            if mem.u32(current + D.E_RENDER):
                cpu.call(A.labels['r_catalog_mission_line'], args=(current, 0x01070000))
                rows.append(mem.cstr(0x01070000))
            else: rows.append(mem.cstr(mem.u32(current + D.E_NAME)))
            current = mem.u32(current + D.E_NEXT)
        return rows
    # First prove that the real native filter includes a Spider-Man mission
    # for Venom, which is the gap the requested video behavior must correct.
    mem.w32(CTRL + D.CONTROLLER_HERO_TYPE, 2)
    cpu.call(address, args=(CONDS,)); assert cpu.r[2] == 1
    assert catalog(2) == ['UNLOAD CURRENT MISSION'] + VENOM
    assert catalog(1) == ['UNLOAD CURRENT MISSION'] + SPIDEY
    # A hero swap must reset a retained page before listing the new hero.
    mem.w32(A.labels['dm_mission_page'], 1)
    assert catalog(2) == ['UNLOAD CURRENT MISSION'] + VENOM
    assert mem.u32(A.labels['dm_mission_page']) == 0
    print('VIDEO HERO MISSION TESTS PASSED; steps:', cpu.steps)


if __name__ == '__main__': run()
