"""Live retail AI parameter browser, following the prerelease debug menu.

SLES_536.72 evidence: ai_core ctor 435780, info_node ctor 49AA08,
param lookup 499348. These offsets deliberately differ from the beta ELF.
The two child pools preserve parent entries across nested navigation.
"""
from types import SimpleNamespace
from asm5900 import Ref

AI_LIST = 0x69C390
SCE_OPEN, SCE_WRITE, SCE_CLOSE = 0x60ADF8, 0x60B698, 0x60B080
PAGE_SIZE = 32
POOL_SIZE = PAGE_SIZE + 4
DYNAMIC_MENUS = ('dm_ai_menu', 'dm_ai_actor_menu', 'dm_ai_params_menu')
MENUS = DYNAMIC_MENUS


def emit_code(A, S, C):
    D = SimpleNamespace(**C)
    G = C['G']

    def call(target):
        A.jal(target); A.nop()

    # Inline full-range checks; all runtime pointers must be aligned EE RAM.
    def ptr(reg, size, fail, aligned=True):
        A.li('t6', 0x100000); A.sltu('t7', reg, 't6')
        A.bnez('t7', fail); A.nop()
        A.li('t6', 0x02000000 - size + 1); A.sltu('t7', reg, 't6')
        A.beqz('t7', fail); A.nop()
        if aligned:
            A.andi('t7', reg, 3); A.bnez('t7', fail); A.nop()

    def alloc(level, name=None, typ='T_ACTION'):
        if name is not None: A.la('a1', S(name))
        A.li('a2', C[typ])
        if level == 'root': call('dm_new_dyn')
        else:
            A.la('a0', 'dm_ai_' + level + '_pool_desc'); call('dm_alloc')

    def add(level):
        menu = 'dm_ai_menu' if level == 'root' else 'dm_ai_' + level + '_menu'
        A.la('a0', menu); A.move('a1', 'v0'); call('dm_add_entry')

    def reset_child(level, parent):
        A.la('t0', 'dm_ai_' + level + '_pool_desc'); A.sw('zero', 4, 't0')
        A.lw_abs('s5', 'dm_ai_' + level + '_entry')
        A.la('a0', 'dm_ai_' + level + '_menu'); A.lw('a1', D.E_NAME, 's5')
        A.li('a2', 1); call('dm_menu_reset')
        A.la('t0', parent); A.la('t1', 'dm_ai_' + level + '_menu')
        A.sw('t0', D.M_PARENT, 't1'); A.sw('t1', D.E_SUBMENU, 's5')

    def paging(level, has_more_reg):
        skip = A.newlabel('ai_no_prev')
        A.lw_abs('t0', 'dm_ai_' + level + '_page')
        A.beqz('t0', skip); A.nop()
        alloc(level, '--Previous page--')
        A.la('t0', 'h_ai_' + level + '_prev'); A.sw('t0', D.E_HANDLER, 'v0'); add(level)
        A.label(skip)
        skip = A.newlabel('ai_no_more')
        A.beqz(has_more_reg, skip); A.nop()
        alloc(level, '--More--')
        A.la('t0', 'h_ai_' + level + '_next'); A.sw('t0', D.E_HANDLER, 'v0'); add(level)
        A.label(skip)

    # Read-only membership check does not dereference a stale candidate core.
    f = A.func('dm_ai_core_live')
    A.lw_abs('t0', AI_LIST); ptr('t0', 8, '.aic_no')
    A.lw('t0', 4, 't0'); ptr('t0', 12, '.aic_no')
    A.lw('t1', 0, 't0'); A.li('t5', 16384)
    A.label('.aic_loop')
    A.beq('t1', 't0', '.aic_no'); A.nop()
    ptr('t1', 12, '.aic_no')
    A.lw('t2', 8, 't1'); A.beq('t2', 'a0', '.aic_found'); A.nop()
    A.lw('t1', 0, 't1'); A.addiu('t5', 't5', -1)
    A.bgtz('t5', '.aic_loop'); A.nop()
    A.label('.aic_no'); A.move('v0', 'zero'); f.ret()
    A.label('.aic_found'); ptr('a0', 0x68, '.aic_no')
    A.lw('v0', 0x58, 'a0'); ptr('v0', 0x20, '.aic_no')
    A.lw('t2', 4, 'v0'); A.andi('t2', 't2', 0x800)
    A.bnez('t2', '.aic_no'); A.nop()
    f.end()

    # Existing pointer, owner and handle must still name the selected actor.
    f = A.func('dm_ai_selected_live', saves=['s0'])
    A.lw_abs('s0', 'dm_ai_core'); A.move('a0', 's0'); call('dm_ai_core_live')
    A.beqz('v0', f.epi); A.nop()
    A.lw_abs('t0', 'dm_ai_owner'); A.bne('v0', 't0', '.ais_no'); A.nop()
    A.lw('t0', D.ENTITY_HANDLE, 'v0'); A.lw_abs('t1', 'dm_ai_handle')
    A.bne('t0', 't1', '.ais_no'); A.nop()
    A.li('v0', 1); f.ret()
    A.label('.ais_no'); A.move('v0', 'zero'); f.end()

    for level, label in (('root', 'p_ai'), ('actor', 'p_ai_actor'), ('params', 'p_ai_params')):
        f = A.func(label)
        A.sw_abs('a0', 'dm_ai_' + level + '_entry')
        A.sw_abs('zero', 'dm_ai_' + level + '_page')
        if level == 'actor':
            A.lw('t0', D.E_ID, 'a0'); A.sw_abs('t0', 'dm_ai_core')
            A.lw('t0', D.E_VALUE, 'a0'); A.sw_abs('t0', 'dm_ai_owner')
            A.lw('t0', D.E_MIN, 'a0'); A.sw_abs('t0', 'dm_ai_handle')
        if level == 'params':
            A.lw('t0', D.E_ID, 'a0'); A.sw_abs('t0', 'dm_ai_block')
        call('dm_ai_' + level + '_page_build'); f.end()
        for direction, delta in (('prev', -1), ('next', 1)):
            f = A.func('h_ai_' + level + '_' + direction)
            A.lw_abs('t0', 'dm_ai_' + level + '_page'); A.addiu('t0', 't0', delta)
            A.sw_abs('t0', 'dm_ai_' + level + '_page')
            call('dm_ai_' + level + '_page_build'); f.end()

    f = A.func('dm_ai_root_page_build', saves=['s0', 's1', 's2', 's3', 's4', 's5', 's6'])
    A.lw_abs('a0', 'dm_ai_root_entry'); A.la('a1', 'dm_ai_menu')
    A.la('a2', S('AI')); A.move('a3', 'zero'); call('dm_dyn_menu')
    A.la('t0', 'dm_root_menu'); A.la('t1', 'dm_ai_menu'); A.sw('t0', D.M_PARENT, 't1')
    A.move('s4', 'zero'); A.move('s6', 'zero')
    A.lw_abs('s0', AI_LIST); ptr('s0', 8, '.air_pages')
    A.lw('s0', 4, 's0'); ptr('s0', 12, '.air_pages')
    A.lw('s1', 0, 's0'); A.lw_abs('s3', 'dm_ai_root_page'); A.sll('s3', 's3', 5)
    A.li('s5', 16384)
    A.label('.air_loop')
    A.beq('s1', 's0', '.air_pages'); A.nop()
    ptr('s1', 12, '.air_pages')
    A.lw('s2', 8, 's1'); ptr('s2', 0x68, '.air_next')
    A.lw('t0', 0x58, 's2'); ptr('t0', 0x20, '.air_next')
    A.lw('t1', 4, 't0'); A.andi('t1', 't1', 0x800)
    A.bnez('t1', '.air_next'); A.nop()
    A.beqz('s3', '.air_add'); A.nop()
    A.addiu('s3', 's3', -1); A.b('.air_next'); A.nop()
    A.label('.air_add'); A.sltiu('t1', 's4', PAGE_SIZE)
    A.beqz('t1', '.air_more'); A.nop()
    A.sll('t1', 's4', 4); A.la('a0', 'dm_ai_root_names'); A.addu('a0', 'a0', 't1')
    A.li('a1', 16); A.la('a2', S('0x%08x')); A.lw('a3', 0x10, 't0'); call(G['snprintf'])
    A.sll('t1', 's4', 4); A.la('a1', 'dm_ai_root_names'); A.addu('a1', 'a1', 't1')
    alloc('root', typ='T_SUB'); A.beqz('v0', '.air_pages'); A.nop()
    A.sw('s2', D.E_ID, 'v0'); A.lw('t0', 0x58, 's2'); A.sw('t0', D.E_VALUE, 'v0')
    A.lw('t0', D.ENTITY_HANDLE, 't0'); A.sw('t0', D.E_MIN, 'v0')
    A.la('t0', 'p_ai_actor'); A.sw('t0', D.E_POPULATE, 'v0'); add('root')
    A.addiu('s4', 's4', 1)
    A.label('.air_next'); A.lw('s1', 0, 's1'); A.addiu('s5', 's5', -1)
    A.bgtz('s5', '.air_loop'); A.nop()
    A.b('.air_pages'); A.nop()
    A.label('.air_more'); A.li('s6', 1)
    A.label('.air_pages'); paging('root', 's6')
    A.bnez('s4', f.epi); A.nop()
    alloc('root', '--None defined--'); add('root'); f.end()

    f = A.func('dm_ai_actor_page_build', saves=['s0', 's1', 's2', 's3', 's4', 's5', 's6'])
    reset_child('actor', 'dm_ai_menu')
    call('dm_ai_selected_live'); A.beqz('v0', '.aia_empty'); A.nop()
    A.lw_abs('s0', 'dm_ai_core')
    alloc('actor', '-Core params', 'T_SUB')
    A.addiu('t0', 's0', 0x44); A.sw('t0', D.E_ID, 'v0')
    A.la('t0', 'p_ai_params'); A.sw('t0', D.E_POPULATE, 'v0'); add('actor')
    A.move('s6', 'zero'); A.lw('s0', 0x54, 's0'); A.sw_abs('s0', 'dm_ai_inodes')
    A.beqz('s0', '.aia_pages'); A.nop()
    ptr('s0', 12, '.aia_pages')
    A.lw('s1', 8, 's0'); A.lw('s2', 4, 's0')
    A.sltiu('t0', 's2', 4097); A.beqz('t0', '.aia_pages'); A.nop()
    A.lw_abs('s3', 'dm_ai_actor_page'); A.sll('s3', 's3', 5); A.move('s4', 'zero')
    A.label('.aia_loop'); A.sltu('t0', 's3', 's2'); A.beqz('t0', '.aia_pages'); A.nop()
    A.sltiu('t0', 's4', PAGE_SIZE); A.beqz('t0', '.aia_more'); A.nop()
    A.sll('t0', 's3', 2); A.addu('t0', 's1', 't0'); ptr('t0', 4, '.aia_pages')
    A.lw('s5', 0, 't0'); ptr('s5', 0x1C, '.aia_pages')
    A.sll('t0', 's4', 5); A.la('a0', 'dm_ai_actor_names'); A.addu('a0', 'a0', 't0')
    A.li('a1', 32); A.la('a2', S('0x%08x inode params')); A.lw('a3', 4, 's5'); call(G['snprintf'])
    A.sll('t0', 's4', 5); A.la('a1', 'dm_ai_actor_names'); A.addu('a1', 'a1', 't0')
    alloc('actor', typ='T_SUB'); A.beqz('v0', '.aia_pages'); A.nop()
    A.addiu('t0', 's5', 0x10); A.sw('t0', D.E_ID, 'v0')
    A.la('t0', 'p_ai_params'); A.sw('t0', D.E_POPULATE, 'v0'); add('actor')
    A.addiu('s4', 's4', 1); A.addiu('s3', 's3', 1); A.b('.aia_loop'); A.nop()
    A.label('.aia_more'); A.li('s6', 1)
    A.label('.aia_pages'); paging('actor', 's6'); f.ret()
    A.label('.aia_empty'); alloc('actor', '--Actor unloaded--'); add('actor'); f.end()

    # v0=true when selected block still belongs to the live core/inode vector.
    f = A.func('dm_ai_block_live', saves=['s0'])
    call('dm_ai_selected_live'); A.beqz('v0', f.epi); A.nop()
    A.lw_abs('s0', 'dm_ai_block'); A.lw_abs('t0', 'dm_ai_core')
    A.addiu('t1', 't0', 0x44); A.beq('t1', 's0', '.aib_yes'); A.nop()
    A.lw('t0', 0x54, 't0'); ptr('t0', 12, '.aib_no')
    A.lw('t1', 4, 't0'); A.lw('t0', 8, 't0')
    A.sltiu('t2', 't1', 4097); A.beqz('t2', '.aib_no'); A.nop()
    A.label('.aib_loop'); A.blez('t1', '.aib_no'); A.nop()
    ptr('t0', 4, '.aib_no'); A.lw('t2', 0, 't0'); ptr('t2', 0x1C, '.aib_no')
    A.addiu('t2', 't2', 0x10); A.beq('t2', 's0', '.aib_yes'); A.nop()
    A.addiu('t0', 't0', 4); A.addiu('t1', 't1', -1); A.b('.aib_loop'); A.nop()
    A.label('.aib_no'); A.move('v0', 'zero'); f.ret()
    A.label('.aib_yes'); A.li('v0', 1); f.end()

    f = A.func('dm_ai_params_page_build', saves=['s0', 's1', 's2', 's3', 's4', 's5', 's6'])
    reset_child('params', 'dm_ai_actor_menu')
    A.sw_abs('zero', 'dm_ai_array'); A.sw_abs('zero', 'dm_ai_records'); A.sw_abs('zero', 'dm_ai_count')
    call('dm_ai_block_live'); A.beqz('v0', '.aip_empty'); A.nop()
    A.lw_abs('t0', 'dm_ai_block'); A.lw('s0', 4, 't0'); A.sw_abs('s0', 'dm_ai_array')
    ptr('s0', 12, '.aip_empty')
    A.lw('s1', 8, 's0'); A.lw('s2', 4, 's0')
    A.sltiu('t0', 's2', 4097); A.beqz('t0', '.aip_empty'); A.nop()
    A.sw_abs('s1', 'dm_ai_records'); A.sw_abs('s2', 'dm_ai_count')
    A.lw_abs('s3', 'dm_ai_params_page'); A.sll('s3', 's3', 5)
    A.move('s4', 'zero'); A.move('s6', 'zero')
    A.label('.aip_loop'); A.sltu('t0', 's3', 's2'); A.beqz('t0', '.aip_pages'); A.nop()
    A.sltiu('t0', 's4', PAGE_SIZE); A.beqz('t0', '.aip_more'); A.nop()
    A.sll('t0', 's3', 2); A.addu('s0', 's1', 't0'); ptr('s0', 4, '.aip_pages')
    A.lw('s5', 0, 's0'); ptr('s5', 12, '.aip_pages')
    A.sll('t0', 's4', 4); A.la('a0', 'dm_ai_param_names'); A.addu('a0', 'a0', 't0')
    A.li('a1', 16); A.la('a2', S('0x%08x')); A.lw('a3', 8, 's5'); call(G['snprintf'])
    A.sll('t0', 's4', 4); A.la('a1', 'dm_ai_param_names'); A.addu('a1', 'a1', 't0')
    alloc('params'); A.beqz('v0', '.aip_pages'); A.nop()
    A.sw('s0', D.E_SUBMENU, 'v0'); A.sw('s5', D.E_VALUE, 'v0')
    A.lw('t0', 4, 's5'); A.sw('t0', D.E_POPULATE, 'v0')
    A.beqz('t0', '.aip_float'); A.nop()
    A.li('t1', 1); A.beq('t0', 't1', '.aip_int'); A.nop()
    A.la('t0', 'r_ai_param'); A.sw('t0', D.E_RENDER, 'v0'); A.b('.aip_add'); A.nop()
    A.label('.aip_float'); A.li('t0', D.T_FLOATP); A.sw('t0', D.E_TYPE, 'v0')
    A.li('t0', 0x3E99999A); A.sw('t0', D.E_ID, 'v0')
    A.li('t0', 0x41F00000); A.sw('t0', D.E_POPULATE, 'v0')  # float step scale 30
    A.li('t0', 0xFF7FFFFF); A.sw('t0', D.E_MIN, 'v0')
    A.li('t0', 0x7F7FFFFF); A.sw('t0', D.E_MAX, 'v0'); A.b('.aip_add'); A.nop()
    A.label('.aip_int'); A.li('t0', D.T_INTP); A.sw('t0', D.E_TYPE, 'v0')
    A.li('t0', -2147483648); A.sw('t0', D.E_MIN, 'v0')
    A.li('t0', 2147483647); A.sw('t0', D.E_MAX, 'v0')
    A.label('.aip_add'); add('params')
    A.addiu('s4', 's4', 1); A.addiu('s3', 's3', 1); A.b('.aip_loop'); A.nop()
    A.label('.aip_more'); A.li('s6', 1)
    A.label('.aip_pages'); paging('params', 's6')
    alloc('params', '--Export this block--')
    A.la('t0', 'h_ai_export'); A.sw('t0', D.E_HANDLER, 'v0'); add('params'); f.ret()
    A.label('.aip_empty'); alloc('params', '--None defined--'); add('params'); f.end()

    # Structured parameters are read-only just as in the native menu. Formatting
    # uses the existing integer-only float formatter, avoiding PS2 vararg doubles.
    f = A.func('dm_ai_float_text', locals_size=D.E_SIZE)
    for off in range(0, D.E_SIZE, 4): A.sw('zero', off, 'sp')
    A.sw('a0', D.E_VALUE, 'sp'); A.li('t0', D.T_FLOATP); A.sw('t0', D.E_TYPE, 'sp')
    A.move('a0', 'sp'); call('dm_value_text'); f.end()

    f = A.func('r_ai_param', saves=['s0', 's1', 's2'])
    A.lw('s0', D.E_VALUE, 'a0'); A.move('s1', 'a1')
    A.lw('t0', 4, 's0'); A.li('t1', 2); A.beq('t0', 't1', '.arp_hash'); A.nop()
    A.li('t1', 3); A.beq('t0', 't1', '.arp_string'); A.nop()
    A.li('t1', 4); A.beq('t0', 't1', '.arp_vector'); A.nop()
    A.li('t1', 5); A.beq('t0', 't1', '.arp_variance'); A.nop()
    A.lw('a3', 0, 's0'); A.la('a2', S('0x%08x (opaque)')); A.b('.arp_format'); A.nop()
    A.label('.arp_hash'); A.lw('a3', 0, 's0'); A.la('a2', S('0x%08x (hash)'))
    A.b('.arp_format'); A.nop()
    A.label('.arp_string'); A.lw('s0', 0, 's0'); ptr('s0', 32, '.arp_unavailable', False)
    A.la('a0', 'dm_ai_format0'); A.move('a1', 's0'); call('dm_catalog_copy32')
    A.la('a3', 'dm_ai_format0'); A.la('a2', S('%s (fixedstring)')); A.b('.arp_format'); A.nop()
    A.label('.arp_vector'); A.li('s2', 3); A.b('.arp_tuple'); A.nop()
    A.label('.arp_variance'); A.li('s2', 2)
    A.label('.arp_tuple'); A.lw('s0', 0, 's0'); ptr('s0', 12, '.arp_unavailable')
    A.move('a0', 's0'); A.la('a1', 'dm_ai_format0'); call('dm_ai_float_text')
    A.addiu('a0', 's0', 4); A.la('a1', 'dm_ai_format1'); call('dm_ai_float_text')
    A.li('t0', 2); A.beq('s2', 't0', '.arp_pair'); A.nop()
    A.addiu('a0', 's0', 8); A.la('a1', 'dm_ai_format2'); call('dm_ai_float_text')
    A.la('a2', S('(%s %s %s) (vector3d)')); A.la('t1', 'dm_ai_format2')
    A.b('.arp_tuple_format'); A.nop()
    A.label('.arp_pair'); A.la('a2', S('(b%s v%s) (float variance)'))
    A.label('.arp_tuple_format'); A.la('a3', 'dm_ai_format0'); A.la('t0', 'dm_ai_format1')
    A.b('.arp_format'); A.nop()
    A.label('.arp_unavailable'); A.la('a2', S('%s')); A.la('a3', S('<unavailable>'))
    A.label('.arp_format'); A.move('a0', 's1'); A.li('a1', 64); call(G['snprintf']); f.end()

    # Native sce* entry points verified from retail os_file methods. Explicit
    # host: output avoids os_file redirecting a write to the read-only CD device.
    # The emulator/devkit must provide host filesystem access, as for the beta.
    f = A.func('dm_ai_write_all', saves=['s0', 's1', 's2'])
    A.move('s0', 'a0'); A.move('s1', 'a1'); A.move('s2', 'a2')
    A.label('.aiw_loop'); A.beqz('s2', '.aiw_ok'); A.nop()
    A.move('a0', 's0'); A.move('a1', 's1'); A.move('a2', 's2'); call(SCE_WRITE)
    A.blez('v0', '.aiw_fail'); A.nop()
    A.sltu('t0', 's2', 'v0'); A.bnez('t0', '.aiw_fail'); A.nop()
    A.addu('s1', 's1', 'v0'); A.subu('s2', 's2', 'v0'); A.b('.aiw_loop'); A.nop()
    A.label('.aiw_ok'); A.li('v0', 1); f.ret()
    A.label('.aiw_fail'); A.move('v0', 'zero'); f.end()

    f = A.func('h_ai_export', saves=['s0', 's1', 's2', 's3', 's4', 's5'], locals_size=D.E_SIZE)
    A.move('s5', 'a0'); A.li('t0', -1); A.sw_abs('t0', 'dm_ai_export_status')
    call('dm_ai_block_live'); A.beqz('v0', '.aix_failed'); A.nop()
    A.lw_abs('t0', 'dm_ai_block'); A.lw('s0', 4, 't0'); ptr('s0', 12, '.aix_failed')
    A.lw('s1', 8, 's0'); A.lw('s2', 4, 's0')
    A.sltiu('t0', 's2', 4097); A.beqz('t0', '.aix_failed'); A.nop()
    A.lw_abs('t0', 'dm_ai_owner'); A.lw('a3', 0x10, 't0')
    A.la('a0', 'dm_ai_export_line'); A.li('a1', 192)
    A.la('a2', S('host:param_dump_0x%08x.txt')); call(G['snprintf'])
    A.la('a0', 'dm_ai_export_line'); A.li('a1', 0x602); A.move('a2', 'zero'); call(SCE_OPEN)
    A.bltz('v0', '.aix_failed'); A.nop()
    A.move('s3', 'v0')
    A.la('a0', 'dm_ai_export_line'); A.li('a1', 192)
    A.la('a2', S('// Parameter list for 0x%08x\r\n'))
    A.lw_abs('t0', 'dm_ai_owner'); A.lw('a3', 0x10, 't0'); call(G['snprintf'])
    A.move('a2', 'v0'); A.move('a0', 's3'); A.la('a1', 'dm_ai_export_line'); call('dm_ai_write_all')
    A.beqz('v0', '.aix_close_failed'); A.nop()
    for off in range(0, D.E_SIZE, 4): A.sw('zero', off, 'sp')
    A.label('.aix_loop'); A.beqz('s2', '.aix_close_ok'); A.nop()
    ptr('s1', 4, '.aix_close_failed'); A.lw('s4', 0, 's1'); ptr('s4', 12, '.aix_close_failed')
    A.lw('t0', 4, 's4'); A.sltiu('t1', 't0', 8); A.beqz('t1', '.aix_close_failed'); A.nop()
    A.sw('s4', D.E_VALUE, 'sp'); A.sw('zero', D.E_RENDER, 'sp')
    A.li('t1', D.T_FLOATP); A.beqz('t0', '.aix_scalar'); A.nop()
    A.li('t1', 1); A.beq('t0', 't1', '.aix_integer'); A.nop()
    A.la('t1', 'r_ai_param'); A.sw('t1', D.E_RENDER, 'sp')
    A.li('t1', D.T_ACTION); A.b('.aix_scalar'); A.nop()
    A.label('.aix_integer'); A.li('t1', D.T_INTP)
    A.label('.aix_scalar'); A.sw('t1', D.E_TYPE, 'sp')
    A.move('a0', 'sp'); A.la('a1', 'dm_ai_export_value'); call('dm_value_text')
    A.lw('t0', 4, 's4'); A.sll('t0', 't0', 2); A.la('t1', 'dm_ai_type_names')
    A.addu('t0', 't0', 't1'); A.lw('a3', 0, 't0')
    A.lw('t0', 8, 's4'); A.la('t1', 'dm_ai_export_value')
    A.la('a0', 'dm_ai_export_line'); A.li('a1', 192); A.la('a2', S('%s 0x%08x %s\r\n')); call(G['snprintf'])
    A.move('a2', 'v0'); A.move('a0', 's3'); A.la('a1', 'dm_ai_export_line'); call('dm_ai_write_all')
    A.beqz('v0', '.aix_close_failed'); A.nop()
    A.addiu('s1', 's1', 4); A.addiu('s2', 's2', -1); A.b('.aix_loop'); A.nop()
    A.label('.aix_close_ok'); A.move('a0', 's3'); call(SCE_CLOSE)
    A.bltz('v0', '.aix_failed'); A.nop()
    A.li('t0', 1); A.sw_abs('t0', 'dm_ai_export_status'); call('dm_hide'); f.ret()
    A.label('.aix_close_failed'); A.move('a0', 's3'); call(SCE_CLOSE)
    A.label('.aix_failed'); A.la('t0', S('Export failed (check host:)')); A.sw('t0', D.E_NAME, 's5'); f.end()

    # Call before both input and render. An entry never writes through a stale
    # pointer after actors, inode vectors or parameter arrays are replaced.
    f = A.func('dm_ai_validate', saves=['s0', 's1'])
    A.lw_abs('s0', 'dm_active_menu'); A.la('t0', 'dm_ai_actor_menu')
    A.beq('s0', 't0', '.aiv_actor'); A.nop()
    A.la('t0', 'dm_ai_params_menu'); A.bne('s0', 't0', f.epi); A.nop()
    call('dm_ai_block_live'); A.beqz('v0', '.aiv_hide'); A.nop()
    A.lw_abs('t0', 'dm_ai_block'); A.lw('t0', 4, 't0'); A.lw_abs('t1', 'dm_ai_array')
    A.bne('t0', 't1', '.aiv_hide'); A.nop()
    A.beqz('t0', f.epi); A.nop()
    ptr('t0', 12, '.aiv_hide')
    A.lw('t1', 8, 't0'); A.lw_abs('t2', 'dm_ai_records'); A.bne('t1', 't2', '.aiv_hide'); A.nop()
    A.lw('t1', 4, 't0'); A.lw_abs('t2', 'dm_ai_count'); A.bne('t1', 't2', '.aiv_hide'); A.nop()
    A.lw('s0', D.M_FIRST, 's0'); A.li('s1', POOL_SIZE)
    A.label('.aiv_loop'); A.beqz('s0', f.epi); A.nop()
    A.lw('t0', D.E_SUBMENU, 's0'); A.beqz('t0', '.aiv_next'); A.nop()
    ptr('t0', 4, '.aiv_hide'); A.lw('t0', 0, 't0'); A.lw('t1', D.E_VALUE, 's0')
    A.bne('t0', 't1', '.aiv_hide'); A.nop()
    ptr('t0', 12, '.aiv_hide'); A.lw('t1', 4, 't0'); A.lw('t2', D.E_POPULATE, 's0')
    A.lw('t3', D.E_TYPE, 's0'); A.addiu('t3', 't3', -D.T_FLOATP)
    A.movz('t2', 'zero', 't3')  # Float entry metadata holds scale; native type is zero.
    A.bne('t1', 't2', '.aiv_hide'); A.nop()
    A.bnez('t1', '.aiv_next'); A.nop()
    A.lw('t0', 0, 't0'); A.li('t1', 0x7F800000); A.and_('t0', 't0', 't1')
    A.beq('t0', 't1', '.aiv_hide'); A.nop()
    A.label('.aiv_next'); A.lw('s0', D.E_NEXT, 's0'); A.addiu('s1', 's1', -1)
    A.bgtz('s1', '.aiv_loop'); A.nop()
    A.b('.aiv_hide'); A.nop()
    A.label('.aiv_actor'); call('dm_ai_selected_live'); A.bnez('v0', f.epi); A.nop()
    A.label('.aiv_hide'); call('dm_hide'); f.end()


def emit_menus(A, S, C):
    A.la('a0', 'dm_root_menu'); A.move('a1', 'zero')
    A.la('a2', S('AI')); A.la('a3', 'p_ai'); A.jal('dm_add_sub'); A.nop()


def emit_data(A, S, C):
    for level in ('actor', 'params'):
        A.align(4); A.label('dm_ai_' + level + '_pool_desc')
        A.word(Ref('dm_ai_' + level + '_pool')); A.word(0); A.word(POOL_SIZE)
    A.label('dm_ai_type_names')
    for name in ('float', 'int', 'string_hash', 'fixedstring', 'vector3d', 'float_variance', 'entity', 'pointer'):
        A.word(Ref(S(name)))


def emit_bss(A, C):
    for label in ('root_entry', 'actor_entry', 'params_entry', 'root_page', 'actor_page',
                  'params_page', 'core', 'owner', 'handle', 'block', 'inodes', 'array',
                  'records', 'count', 'export_status'):
        A.label('dm_ai_' + label); A.word(0)
    for level in ('actor', 'params'):
        A.align(16); A.label('dm_ai_' + level + '_pool'); A.space(POOL_SIZE * C['E_SIZE'])
    for label, size in (('root_names', 16), ('actor_names', 32), ('param_names', 16)):
        A.align(16); A.label('dm_ai_' + label); A.space(PAGE_SIZE * size)
    for n in range(3):
        A.label('dm_ai_format%d' % n); A.space(32)
    A.label('dm_ai_export_line'); A.space(192)
    A.label('dm_ai_export_value'); A.space(64)
