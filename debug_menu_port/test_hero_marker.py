"""Current-hero markers use retail game settings, and remain exclusive on swap."""
import dm_build as D
from emu import Mem, CPU, c_format


def run():
    A, blob = D.build(); mem = Mem(); mem.write(D.BASE, blob)
    mem.write(0x01000000, bytes(0x10000)); mem.write(0x01E00000, bytes(0x100000))
    cpu = CPU(mem, D.BASE, A.labels['dm_end'])
    GAME, SETTINGS, ENTRY, TEXT = 0x01000000, 0x01001000, 0x01002000, 0x01002100
    mem.w32(D.G['g_game_ptr'], GAME); mem.w32(GAME + D.GAME_SETTINGS, SETTINGS)
    mem.w32(ENTRY, TEXT); mem.write(TEXT, b'Hero Select\0')
    packs = {'ultimate_spiderman', 'venom', 'peter_parker', 'peter_hooded'}
    hashes = {}
    def hash_init(c):
        name = mem.cstr(c.r[6] & 0xFFFFFFFF)
        h = D.HEROES.index(name) + 1; hashes[h] = name
        mem.w32(c.r[4] & 0xFFFFFFFF, h)
    cpu.stubs[D.G['string_hash_init']] = hash_init
    def pack_exists(c):
        p = c.r[4] & 0xFFFFFFFF; assert mem.u32(p + 4) == 0x19
        c.r[2] = int(hashes[mem.u32(p)] in packs)
    cpu.stubs[D.G['get_pack_file_stats']] = pack_exists
    def compare(c):
        a, b = (mem.cstr(c.r[i] & 0xFFFFFFFF).lower() for i in (4, 5))
        c.r[2] = ((a > b) - (a < b)) & 0xFFFFFFFFFFFFFFFF
    cpu.stubs[D.G['strcasecmp']] = compare
    def snprintf(c):
        value = c_format(mem.cstr(c.r[6] & 0xFFFFFFFF), c.r[7:12], mem)
        mem.write(c.r[4] & 0xFFFFFFFF, value.encode() + b'\0'); c.r[2] = len(value)
    cpu.stubs[D.G['snprintf']] = snprintf
    def call(name, *args): return cpu.call(A.labels[name], args=args)
    def entries():
        out = {}; p = mem.u32(A.labels['dm_hero_menu'] + D.M_FIRST)
        while p:
            out[mem.cstr(mem.u32(p))] = p; p = mem.u32(p + D.E_NEXT)
        return out
    def rebuild(name):
        mem.write(SETTINGS + 0x8A8, bytes(32))
        mem.write(SETTINGS + 0x8A8, name.encode()[:32])
        call('p_hero', ENTRY); return entries()
    def active(rows): return [name for name, p in rows.items() if mem.u32(p + D.E_VALUE)]
    rows = rebuild('ultimate_spiderman')
    assert set(rows) == packs and active(rows) == ['ultimate_spiderman'], (rows, active(rows))
    call('dm_value_text', rows['ultimate_spiderman'], 0x01003000)
    assert mem.cstr(0x01003000) == 'True'
    call('dm_value_text', rows['venom'], 0x01003000)
    assert mem.cstr(0x01003000) == 'False'
    call('dm_on_select', rows['venom'])
    assert active(rows) == ['venom'] and mem.u32(A.labels['dm_hero_status']) == 1
    assert mem.cstr(mem.u32(A.labels['dm_hero_name'])) == 'venom'
    # The pending request cannot be toggled off or replaced by key repeat.
    call('dm_on_select', rows['venom']); assert active(rows) == ['venom']
    call('dm_on_select', rows['peter_parker']); assert active(rows) == ['venom']
    assert mem.cstr(mem.u32(A.labels['dm_hero_name'])) == 'venom'
    mem.w32(A.labels['dm_hero_status'], 0)
    # Mission changes/reopened menu read the actual native hero setting.
    rows = rebuild('PETER_HOODED'); assert active(rows) == ['peter_hooded']
    rows = rebuild('venom'); assert active(rows) == ['venom']
    rows = rebuild('unknown_character'); assert active(rows) == []
    rows = rebuild('a' * 32); assert active(rows) == []  # bounded native name
    mem.w32(GAME + D.GAME_SETTINGS, 0); call('p_hero', ENTRY); assert active(entries()) == []
    mem.w32(GAME + D.GAME_SETTINGS, 0x01FFFFF0); call('p_hero', ENTRY); assert active(entries()) == []
    mem.w32(D.G['g_game_ptr'], 0); call('p_hero', ENTRY); assert active(entries()) == []
    print('HERO MARKER TESTS PASSED; steps:', cpu.steps)


if __name__ == '__main__':
    run()
