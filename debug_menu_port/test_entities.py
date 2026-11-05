"""Behavioral scenarios for retail entity variants and typed script variables."""
import struct
import dm_entities as E


def run(ctx):
    mem, cpu, D = (ctx[k] for k in ('mem', 'cpu', 'D'))
    A, G = ctx['A'], ctx['G']
    tap, goto, var = (ctx[k] for k in ('tap', 'goto', 'var'))
    title, state, log = ctx['menu_title'], ctx['state'], ctx['log']
    WORLD, HERO, f2b, b2f = (ctx[k] for k in ('WORLD', 'HERO', 'f2b', 'b2f'))
    mem.write(0x01100000, bytes(0x100000))
    SENTINEL, NODE, VECTOR, VTABLE = 0x01100000, 0x01100100, 0x01100200, 0x01100400
    HAS, GET = 0x01100C00, 0x01100C10
    SHARED_NAME = 0x011F0000
    mem.w32(WORLD + 0x78, SENTINEL)
    mem.w32(SENTINEL, NODE); mem.w32(SENTINEL + 4, NODE)
    mem.w32(NODE, SENTINEL); mem.w32(NODE + 4, SENTINEL)
    # Signed this-adjustments are deliberately nonzero.
    mem.write(VTABLE + 0x540, struct.pack('<h', -4))
    mem.w32(VTABLE + 0x544, HAS)
    mem.write(VTABLE + 0x548, struct.pack('<h', 8))
    mem.w32(VTABLE + 0x54C, GET)
    entities = [HERO] + [0x01110000 + i * 0x200 for i in range(65)]
    interfaces, hashes = {}, {}
    for i, entity in enumerate(entities):
        ifc = 0x01130000 + i * 0x100
        variants = 0x01150000 + i * 0x1000
        mem.w32(entity, VTABLE); mem.w32(entity + 4, 4)
        mem.w32(entity + 0x10, i + 1); hashes[i + 1] = 'hero' if not i else 'entity_%d' % i
        mem.w32(entity + D.ENTITY_HANDLE, 0x1000 + i)
        mem.w32(ifc + 4, entity); mem.w32(ifc + 0xC, variants)
        count = 70 if not i else 2
        mem.write(ifc + 0x10, struct.pack('<H', count))
        for k in range(count):
            h = 0x10000 + i * 0x100 + k
            hashes[h] = 'variant_%d' % k
            mem.w32(variants + 16 * k, h)
        interfaces[entity] = ifc
        mem.w32(VECTOR + i * 4, entity)
    mem.w32(NODE + 8, VECTOR); mem.w32(NODE + 12, VECTOR + len(entities) * 4)

    def has(c):
        entity = (c.r[4] + 4) & 0xFFFFFFFF
        assert entity in interfaces
        c.r[2] = 1
    def get(c):
        c.r[2] = interfaces[(c.r[4] - 8) & 0xFFFFFFFF]
    def hash_text(c):
        name = hashes[mem.u32(c.r[4] & 0xFFFFFFFF)]
        # The real fallback string also uses a shared buffer; names must be copied.
        mem.write(SHARED_NAME, name.encode() + b'\0')
        c.r[2] = SHARED_NAME
    def apply(c):
        log.append(('apply_variant', c.r[4] & 0xFFFFFFFF, c.r[5] & 0xFFFFFFFF))
        mem.w32((c.r[4] & 0xFFFFFFFF) + 0x1C, c.r[5])
    cpu.stubs[HAS], cpu.stubs[GET] = has, get
    cpu.stubs[E.HASH_TEXT], cpu.stubs[E.APPLY_VARIANT] = hash_text, apply

    if var('dm_active_menu'):
        tap(D.DMENU_TOGGLE)
    tap(D.DMENU_TOGGLE); goto('Entity Variants'); tap(D.DMENU_SELECT)
    assert title() == 'Entity Variants'
    assert mem.u32(var('dm_active_menu') + D.M_COUNT) == 65
    goto('hero'); tap(D.DMENU_SELECT)
    assert title() == 'hero'
    assert mem.u32(var('dm_active_menu') + D.M_COUNT) == 65
    goto('More variants'); tap(D.DMENU_SELECT)
    assert mem.u32(var('dm_active_menu') + D.M_COUNT) == 7
    goto('variant_69'); log.clear(); tap(D.DMENU_SELECT)
    assert ('apply_variant', interfaces[HERO], 0x01150000 + 69 * 16) in log
    assert var('dm_active_menu') == 0

    # A separate child pool preserves every parent's entry across Back.
    tap(D.DMENU_TOGGLE); goto('Entity Variants'); tap(D.DMENU_SELECT)
    goto('hero'); tap(D.DMENU_SELECT); tap(D.DMENU_BACK)
    assert title() == 'Entity Variants'
    goto('More entities'); tap(D.DMENU_SELECT)
    assert mem.u32(var('dm_active_menu') + D.M_COUNT) == 3
    goto('entity_65'); tap(D.DMENU_SELECT); goto('variant_1')
    # A removed entity's stale pointer must never reach the native virtual call.
    mem.w32(NODE + 12, VECTOR + 65 * 4)
    log.clear(); tap(D.DMENU_SELECT)
    assert not any(x[0] == 'apply_variant' for x in log)
    tap(D.DMENU_BACK); goto('Previous entities'); tap(D.DMENU_SELECT)
    tap(D.DMENU_BACK); assert title() == 'Debug Menu'

    # Empty/unloaded world produces an empty menu, without touching null fields.
    mem.w32(G['g_world_ptr'], 0)
    goto('Entity Variants'); tap(D.DMENU_SELECT)
    assert mem.u32(var('dm_active_menu') + D.M_COUNT) == 0
    tap(D.DMENU_BACK); mem.w32(G['g_world_ptr'], WORLD)

    CONTAINER, RECORDS, NAMES, VALUES = 0x011A0000, 0x011A1000, 0x011A2000, 0x011A8000
    NUM, HANDLE = 0x011AA000, 0x011AA020
    mem.w32(NUM, NUM + 0x10); mem.w32(NUM + 4, 4); mem.write(NUM + 0x10, b'num\0')
    mem.w32(HANDLE, HANDLE + 0x10); mem.w32(HANDLE + 4, 4); mem.write(HANDLE + 0x10, b'entity\0')
    mem.w32(E.GAME_VARS, CONTAINER); mem.w32(E.SHARED_VARS, 0)
    mem.w32(CONTAINER + 0xC, RECORDS); mem.w32(CONTAINER + 0x10, 66)
    metadata = {}
    for i in range(66):
        name = 'var_%02d' % i
        name_ptr, value_ptr = NAMES + 32 * i, VALUES + 4 * i
        mem.write(name_ptr, name.encode() + b'\0')
        mem.w32(RECORDS + 8 * i, name_ptr); mem.w32(RECORDS + 8 * i + 4, value_ptr)
        mem.w32(value_ptr, f2b(-0.2 if i == 0 else float(i)))
        metadata[name] = (value_ptr, HANDLE if i == 1 else 0 if i == 2 else NUM)
    def lookup(c):
        assert c.r[4] & 0xFFFFFFFF == CONTAINER
        addr, typ = metadata[mem.cstr(c.r[5] & 0xFFFFFFFF)]
        mem.w32(c.r[6] & 0xFFFFFFFF, typ); c.r[2] = addr
    cpu.stubs[E.SCRIPT_LOOKUP] = lookup

    # Script Variables has no public Game entry. Retain direct coverage of the
    # private variable guard helpers without exposing the removed submenu.
    def open_private_variables():
        if not var('dm_active_menu'):
            tap(D.DMENU_TOGGLE)
        mem.w32(A.labels['dm_active_menu'], A.labels['dm_script_menu'])
        cpu.call(A.labels['dm_grab_focus'])
        ctx['frame']()

    goto('Game'); tap(D.DMENU_SELECT)
    entry = mem.u32(var('dm_active_menu') + D.M_FIRST)
    while entry:
        assert mem.cstr(mem.u32(entry + D.E_NAME)) != 'Script Variables'
        entry = mem.u32(entry + D.E_NEXT)
    open_private_variables()
    goto('SHOW_CHUCK_DEBUGGER'); tap(D.DMENU_SELECT)
    assert ctx['flag'](99) == 1
    goto('Game Variables'); tap(D.DMENU_SELECT)
    assert mem.u32(var('dm_active_menu') + D.M_COUNT) == 65
    goto('var_00'); tap(D.DMENU_RIGHT)
    assert abs(b2f(mem.u32(VALUES)) + 0.1) < 0.0001
    assert 'var_00: -0.10' in [t[4] for t in state['texts']]
    # Opaque handle and missing type metadata are never writable.
    before = mem.read(VALUES + 4, 8)
    goto('var_01'); tap(D.DMENU_RIGHT); tap(D.DMENU_SELECT)
    goto('var_02'); tap(D.DMENU_RIGHT); tap(D.DMENU_SELECT)
    assert mem.read(VALUES + 4, 8) == before
    goto('More variables'); tap(D.DMENU_SELECT)
    goto('var_65'); tap(D.DMENU_RIGHT)
    assert abs(b2f(mem.u32(VALUES + 65 * 4)) - 65.1) < 0.0001
    goto('Previous variables'); tap(D.DMENU_SELECT)
    tap(D.DMENU_BACK); assert title() == 'Script Variables'
    goto('Shared Variables'); tap(D.DMENU_SELECT)
    assert mem.u32(var('dm_active_menu') + D.M_COUNT) == 0
    tap(D.DMENU_BACK); goto('Game Variables'); tap(D.DMENU_SELECT)
    goto('var_00'); tap(D.DMENU_FOCUS_TOGGLE)
    snapshot = mem.u32(VALUES)
    mem.w32(E.GAME_VARS, 0)
    ctx['frame']((D.DMENU_RIGHT,))
    assert var('dm_active_menu') == 0 and mem.u32(VALUES) == snapshot
    mem.w32(E.GAME_VARS, CONTAINER)
    open_private_variables()
    goto('Game Variables'); tap(D.DMENU_SELECT); goto('var_00')
    # Even replacing a record without replacing the container closes before edit.
    mem.w32(RECORDS + 4, VALUES + 0x400)
    ctx['frame']((D.DMENU_RIGHT,))
    assert var('dm_active_menu') == 0 and mem.u32(VALUES) == snapshot
    mem.w32(RECORDS + 4, VALUES)
    open_private_variables()
    goto('Game Variables'); tap(D.DMENU_SELECT)
    mem.w32(VALUES, 0x7FC00000)
    ctx['frame']()
    assert var('dm_active_menu') == 0
    mem.w32(VALUES, snapshot)
    # Null-container screens remain navigable rather than hiding repeatedly.
    open_private_variables()
    goto('Shared Variables'); tap(D.DMENU_SELECT)
    assert ctx['menu_title']() == 'Shared Variables'
    tap(D.DMENU_TOGGLE)
    print('ENTITY / SCRIPT TESTS PASSED')
