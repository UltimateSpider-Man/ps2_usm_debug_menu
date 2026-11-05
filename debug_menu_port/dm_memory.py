"""Read-only slab diagnostics reconstructed from the retail allocator lists.

Retail removed beta's diagnostic counters, but retains the actual slab headers.
Snapshots are taken on entering a category; no allocator state is modified.
"""
from asm5900 import Ref

INITIALIZED = 0x698274
PARTIAL, FULL, FREE = 0x74EB6C, 0x74EB70, 0x74EB74
CLASSES = 44
MENUS = ('dm_memory_menu', 'dm_slabs_menu', 'dm_slab_classes')
DYNAMIC_MENUS = ('dm_slab_classes',)
CATEGORIES = ('Full Slabs', 'Partial Slabs', 'Allocated Objects', 'Free Objects')


def emit_code(A, S, C):
    def call(label):
        A.jal(label); A.nop()

    # Read-only value callback: common renderer ABI (entry, 32-byte output).
    f = A.func('r_slab_value')
    A.lw('a3', C['E_VALUE'], 'a0'); A.move('a0', 'a1')
    A.li('a1', 32); A.la('a2', S('%d')); call(C['G']['snprintf'])
    f.end()

    # a0=list header, a1=expected object size (zero for the untyped free list)
    # v0=count, v1=allocated objects, a2=free objects. Invalid lists fail closed.
    f = A.func('dm_slab_list', saves=['s0', 's1', 's2', 's3', 's4', 's5'])
    A.move('s0', 'a0'); A.move('s1', 'a1')
    A.move('s2', 'zero'); A.move('s3', 'zero'); A.move('s4', 'zero')
    A.andi('t0', 's0', 3); A.bnez('t0', '.slab_bad'); A.nop()
    A.li('a1', 12); call('dm_catalog_ram')
    A.beqz('v0', '.slab_bad'); A.nop()
    A.lw('s5', 0, 's0')
    A.label('.slab_walk')
    A.beqz('s5', '.slab_done'); A.nop()
    A.andi('t0', 's5', 3); A.bnez('t0', '.slab_bad'); A.nop()
    A.sltiu('t0', 's2', 8192); A.beqz('t0', '.slab_bad'); A.nop()
    A.move('a0', 's5'); A.li('a1', 0x24); call('dm_catalog_ram')
    A.beqz('v0', '.slab_bad'); A.nop()
    A.lw('t0', 0, 's5'); A.li('t1', 0xE1E1E1E1)
    A.bne('t0', 't1', '.slab_bad'); A.nop()
    A.lw('t0', 0x20, 's5'); A.li('t1', 0x1E1E1E1E)
    A.bne('t0', 't1', '.slab_bad'); A.nop()
    A.lw('t0', 0x1C, 's5'); A.bne('t0', 's0', '.slab_bad'); A.nop()
    A.beqz('s1', '.slab_next'); A.nop()
    A.lhu('t0', 0xA, 's5'); A.bne('t0', 's1', '.slab_bad'); A.nop()
    A.lhu('t0', 0xC, 's5'); A.lhu('t1', 0xE, 's5')
    A.sltu('t2', 't0', 't1'); A.bnez('t2', '.slab_bad'); A.nop()
    A.addu('s3', 's3', 't1'); A.subu('t0', 't0', 't1')
    A.addu('s4', 's4', 't0')
    A.label('.slab_next'); A.addiu('s2', 's2', 1)
    A.lw('s5', 0x14, 's5'); A.b('.slab_walk'); A.nop()
    A.label('.slab_done')
    A.lw('t0', 8, 's0'); A.bne('t0', 's2', '.slab_bad'); A.nop()
    A.move('v0', 's2'); A.move('v1', 's3'); A.move('a2', 's4'); f.ret()
    A.label('.slab_bad'); A.li('v0', -1); A.move('v1', 'zero'); A.move('a2', 'zero')
    f.end()

    f = A.func('dm_slab_snapshot', saves=['s0', 's1', 's2', 's3', 's4', 's5'])
    A.la('s0', 'dm_slab_values'); A.li('s1', 4 * CLASSES + 2)
    A.label('.slab_clear'); A.sw('zero', 0, 's0'); A.addiu('s0', 's0', 4)
    A.nop(); A.nop()
    A.addiu('s1', 's1', -1); A.bnez('s1', '.slab_clear'); A.nop()
    A.lw_abs('t0', INITIALIZED); A.beqz('t0', f.epi); A.nop()
    A.lw_abs('a0', FREE); A.move('a1', 'zero'); call('dm_slab_list')
    A.bltz('v0', '.slab_snapshot_bad'); A.nop()
    A.sw_abs('v0', 'dm_slab_values', 0); A.sw_abs('v0', 'dm_slab_values', 4)
    A.move('s0', 'zero')
    A.label('.slab_class')
    A.sll('s1', 's0', 2); A.addu('s2', 's1', 's1'); A.addu('s2', 's2', 's1')
    A.addiu('s3', 's1', 4); A.la('s4', 'dm_slab_values'); A.addu('s4', 's4', 's1')
    for index, address in enumerate((FULL, PARTIAL)):
        A.lw_abs('a0', address); A.addu('a0', 'a0', 's2')
        A.move('a1', 's3'); call('dm_slab_list')
        A.bltz('v0', '.slab_snapshot_bad'); A.nop()
        A.sw('v0', 8 + index * CLASSES * 4, 's4')
        A.lw_abs('t0', 'dm_slab_values'); A.addu('t0', 't0', 'v0'); A.sw_abs('t0', 'dm_slab_values')
        for reg, offset in (('v1', 8 + 2 * CLASSES * 4), ('a2', 8 + 3 * CLASSES * 4)):
            A.lw('t0', offset, 's4'); A.addu('t0', 't0', reg); A.sw('t0', offset, 's4')
    A.addiu('s0', 's0', 1); A.sltiu('t0', 's0', CLASSES)
    A.bnez('t0', '.slab_class'); A.nop(); f.ret()
    A.label('.slab_snapshot_bad')
    # A negative snapshot is displayed explicitly instead of invented zeros.
    A.li('t0', -1); A.la('t1', 'dm_slab_values'); A.li('t2', 4 * CLASSES + 2)
    A.label('.slab_invalidate'); A.sw('t0', 0, 't1'); A.addiu('t1', 't1', 4)
    A.nop(); A.nop()
    A.addiu('t2', 't2', -1); A.bnez('t2', '.slab_invalidate'); A.nop()
    f.end()

    # Slabs uses permanent entries so child population cannot invalidate Back.
    f = A.func('p_slabs', saves=['s0'])
    A.move('s0', 'a0'); call('dm_slab_snapshot')
    A.lw_abs('t0', 'dm_slab_values'); A.lw_abs('t1', 'dm_slab_total_entry')
    A.sw('t0', C['E_VALUE'], 't1')
    A.lw_abs('t0', 'dm_slab_values', 4); A.lw_abs('t1', 'dm_slab_free_entry')
    A.sw('t0', C['E_VALUE'], 't1')
    A.la('t0', 'dm_slabs_menu'); A.sw('t0', C['E_SUBMENU'], 's0')
    f.end()

    f = A.func('p_slab_class', saves=['s0', 's1', 's2'])
    A.lw('s0', C['E_ID'], 'a0'); A.lw('a2', C['E_NAME'], 'a0')
    A.la('a1', 'dm_slab_classes'); A.move('a3', 'zero'); call('dm_dyn_menu')
    call('dm_slab_snapshot')
    A.sll('t0', 's0', 7); A.sll('t1', 's0', 5); A.addu('t0', 't0', 't1')
    A.sll('t1', 's0', 4); A.addu('t0', 't0', 't1')
    A.la('s0', 'dm_slab_values'); A.addu('s0', 's0', 't0'); A.addiu('s0', 's0', 8)
    A.la('s1', 'tbl_slab_names'); A.li('s2', CLASSES)
    A.label('.slab_entries')
    A.lw('a1', 0, 's1'); A.li('a2', C['T_ACTION']); call('dm_new_dyn')
    A.beqz('v0', f.epi); A.nop()
    A.lw('t0', 0, 's0'); A.sw('t0', C['E_VALUE'], 'v0')
    A.la('t0', 'r_slab_value'); A.sw('t0', C['E_RENDER'], 'v0')
    A.la('a0', 'dm_slab_classes'); A.move('a1', 'v0'); call('dm_add_entry')
    A.addiu('s0', 's0', 4); A.addiu('s1', 's1', 4); A.addiu('s2', 's2', -1)
    A.bnez('s2', '.slab_entries'); A.nop()
    f.end()


def emit_menus(A, S, C):
    def call(label):
        A.jal(label); A.nop()
    for menu, title in (('dm_memory_menu', 'Memory'), ('dm_slabs_menu', 'Slabs')):
        A.la('a0', menu); A.la('a1', S(title)); A.move('a2', 'zero'); call('dm_menu_reset')
    for parent, menu, title, populate in (
        ('dm_root_menu', 'dm_memory_menu', 'Memory', None),
        ('dm_memory_menu', 'dm_slabs_menu', 'Slabs', 'p_slabs')):
        A.la('a0', parent); A.la('a1', menu); A.la('a2', S(title))
        if populate: A.la('a3', populate)
        else: A.move('a3', 'zero')
        call('dm_add_sub')
    for title, label in (('Total Slabs', 'dm_slab_total_entry'), ('Free Slabs', 'dm_slab_free_entry')):
        A.la('a1', S(title)); A.li('a2', C['T_ACTION']); call('dm_new')
        A.sw_abs('v0', label); A.la('t0', 'r_slab_value'); A.sw('t0', C['E_RENDER'], 'v0')
        A.la('a0', 'dm_slabs_menu'); A.move('a1', 'v0'); call('dm_add_entry')
    for index, title in enumerate(CATEGORIES):
        A.la('a0', 'dm_slabs_menu'); A.move('a1', 'zero'); A.la('a2', S(title))
        A.la('a3', 'p_slab_class'); call('dm_add_sub')
        A.li('t0', index); A.sw('t0', C['E_ID'], 'v0')


def emit_data(A, S, C):
    A.align(4); A.label('tbl_slab_names')
    for size in range(4, 177, 4): A.word(Ref(S('%3d byte' % size)))


def emit_bss(A, C):
    A.align(4); A.label('dm_slab_values'); A.space((4 * CLASSES + 2) * 4)
    A.label('dm_slab_total_entry'); A.space(4)
    A.label('dm_slab_free_entry'); A.space(4)
