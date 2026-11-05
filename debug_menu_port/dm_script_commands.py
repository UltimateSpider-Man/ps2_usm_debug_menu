"""Recover the shipped script-authored debug actions from live Chuck metadata.

The PAL CITY_ARENA script retains the original progression and kill-hero
handlers. Mission packs retain their own label/handler pairs. No game variables
or progression counters are substituted for those functions. See the address
and bytecode evidence in _verification/video_reference/script_parity.md.
"""
from types import SimpleNamespace

EXEC_MAP = 0x683410
FIND_FUNC = 0x2F17E0
ADD_THREAD = 0x2F0D8C
TREE_NEXT = 0x10F130
MAX_COMMANDS = 64
NAME_SIZE = 64
DYNAMIC_MENUS = ('dm_script_commands_menu', 'dm_progression_commands_menu')
MENUS = DYNAMIC_MENUS
# Audited original PS2 callback identities and bytecode word counts. Unknown
# callbacks are not enabled by merely embedding a '(debug_menu_entry)' string.
# CITY_ARENA owner 2958857E, V08 mission owner 95BCE7F8; see evidence report.
AUDITED_CALLBACKS = tuple((h, 0x2958857E, n) for h, n in (
    (0xCF3AC036, 16), (0x4E6625F3, 10), (0x6BDF3415, 10),
    (0x1F567ADC, 25), (0xBDA1AE5A, 10), (0x29281842, 10),
    (0x784DB201, 25), (0xC7734BC0, 10), (0x0409B2BC, 10),
    (0x532F4C7B, 25), (0xA254E63A, 10), (0xF4B072A0, 13),
    (0xDD09F19A, 31), (0x7B552518, 25), (0xCA7ABED7, 10),
    (0x360128BF, 10), (0x8526C27E, 10), (0xD44C5C3D, 10),
    (0x2371F5FC, 25), (0x72978FBB, 10), (0xC1BD297A, 25),
    (0x5B451E6B, 10), (0x10E2C339, 10), (0x41A4E476, 10),
    (0x60085CF8, 25), (0xAF2DF6B7, 25),
)) + ((0x671E49B4, 0x95BCE7F8, 13), (0xB6AA998E, 0x95BCE7F8, 16),
      (0xC29E1F28, 0x95BCE7F8, 31))


def name_hash(text):
    value = 0
    for ch in text.lower():
        value = (value * 33 + ord(ch)) & 0xffffffff
    return value


def emit_code(A, S, C):
    D = SimpleNamespace(**C)
    def call(target):
        A.jal(target); A.nop()
    def ptr(reg, fail, aligned=True):
        A.li('t6', 0x100000); A.sltu('t7', reg, 't6')
        A.bnez('t7', fail); A.nop()
        A.li('t6', 0x02000000); A.sltu('t7', reg, 't6')
        A.beqz('t7', fail); A.nop()
        if aligned:
            A.andi('t7', reg, 3); A.bnez('t7', fail); A.nop()

    # Bounded ASCII hash + signature check; zero means not a callback name.
    f = A.func('dm_script_callback_hash')
    ptr('a0', '.sch_no', False)
    A.move('t0', 'a0'); A.move('v0', 'zero'); A.li('t1', 96)
    A.label('.sch_scan')
    A.lbu('t2', 0, 't0'); A.beqz('t2', '.sch_suffix'); A.nop()
    A.addiu('t3', 't2', -65); A.sltiu('t3', 't3', 26)
    A.beqz('t3', '.sch_lower'); A.nop()
    A.addiu('t2', 't2', 32)
    A.label('.sch_lower')
    A.sll('t3', 'v0', 5); A.addu('v0', 'v0', 't3'); A.addu('v0', 'v0', 't2')
    A.addiu('t0', 't0', 1); A.addiu('t1', 't1', -1)
    A.bgtz('t1', '.sch_scan'); A.nop()
    A.b('.sch_no'); A.nop()
    A.label('.sch_suffix')
    A.subu('t2', 't0', 'a0'); A.sltiu('t2', 't2', 19)
    A.bnez('t2', '.sch_no'); A.nop()
    A.addiu('t0', 't0', -18); A.la('t1', S('(debug_menu_entry)'))
    A.label('.sch_compare')
    A.lbu('t2', 0, 't0'); A.lbu('t3', 0, 't1')
    A.bne('t2', 't3', '.sch_no'); A.nop()
    A.beqz('t3', f.epi); A.nop()
    A.addiu('t0', 't0', 1); A.addiu('t1', 't1', 1)
    A.b('.sch_compare'); A.nop()
    A.label('.sch_no'); A.move('v0', 'zero')
    f.end()

    # A copied label is safe to render after its source pack unloads.
    # v0=1 for progression, 0 otherwise; a0 label.
    f = A.func('dm_script_is_progression')
    for n, prefix in enumerate(('start progression ', 'toggle progression ', 'turnon all tokens')):
        next_label = '.sip_next%d' % n
        A.move('t0', 'a0'); A.la('t1', S(prefix))
        A.label('.sip_loop%d' % n)
        A.lbu('t2', 0, 't0'); A.lbu('t3', 0, 't1')
        A.beqz('t3', '.sip_yes'); A.nop()
        A.bne('t2', 't3', next_label); A.nop()
        A.addiu('t0', 't0', 1); A.addiu('t1', 't1', 1)
        A.b('.sip_loop%d' % n); A.nop()
        A.label(next_label)
    A.move('v0', 'zero'); f.ret()
    A.label('.sip_yes'); A.li('v0', 1); f.end()

    # The injected entry has a different ABI from the removed beta entry.
    # Accept only action callbacks which do not access stack-relative values
    # (including their debug_menu_entry parameter). Local-variable callbacks
    # are conservatively excluded too; they need explicit further analysis.
    # a0=vm_executable. Returns 1 only for a well-bounded, linked action.
    f = A.func('dm_script_action_safe')
    ptr('a0', '.sas_no')
    A.lw('t0', 0, 'a0'); ptr('t0', '.sas_no')
    A.lw('t0', 0, 't0'); A.lw('t1', 4, 'a0'); A.lw('t2', 0x14, 'a0')
    A.la('t3', 'dm_script_audited_callbacks'); A.li('t4', len(AUDITED_CALLBACKS))
    A.label('.sas_audit')
    A.lw('t5', 0, 't3'); A.bne('t5', 't1', '.sas_audit_next'); A.nop()
    A.lw('t5', 4, 't3'); A.bne('t5', 't0', '.sas_no'); A.nop()
    A.lw('t5', 8, 't3'); A.bne('t5', 't2', '.sas_no'); A.nop()
    A.b('.sas_audited'); A.nop()
    A.label('.sas_audit_next')
    A.addiu('t3', 't3', 12); A.addiu('t4', 't4', -1)
    A.bgtz('t4', '.sas_audit'); A.nop()
    A.b('.sas_no'); A.nop()
    A.label('.sas_audited')
    A.lw('t0', 12, 'a0'); A.li('t1', 4)
    A.bne('t0', 't1', '.sas_no'); A.nop()
    A.lw('t0', 0x1C, 'a0'); A.andi('t0', 't0', 2)
    A.beqz('t0', '.sas_no'); A.nop()
    A.lw('t0', 0x10, 'a0'); ptr('t0', '.sas_no', False)
    A.andi('t1', 't0', 1); A.bnez('t1', '.sas_no'); A.nop()
    A.lw('t1', 0x14, 'a0'); A.sltiu('t2', 't1', 2049)
    A.beqz('t2', '.sas_no'); A.nop()
    A.beqz('t1', '.sas_no'); A.nop()
    A.sll('t1', 't1', 1); A.addu('t1', 't0', 't1')
    ptr('t1', '.sas_no', False)
    A.label('.sas_loop')
    A.beq('t0', 't1', '.sas_yes'); A.nop()
    A.sltu('t2', 't0', 't1'); A.beqz('t2', '.sas_no'); A.nop()
    A.lhu('t2', 0, 't0'); A.addiu('t0', 't0', 2)
    A.andi('t3', 't2', 0x80); A.beqz('t3', '.sas_kind'); A.nop()
    A.addiu('t0', 't0', 2)
    A.label('.sas_kind')
    A.andi('t2', 't2', 127)
    A.li('t3', 6); A.beq('t2', 't3', '.sas_no'); A.nop()
    A.li('t3', 7); A.beq('t2', 't3', '.sas_no'); A.nop()
    A.sltiu('t3', 't2', 23); A.beqz('t3', '.sas_no'); A.nop()
    A.la('t3', 'dm_script_operand_sizes'); A.addu('t3', 't3', 't2')
    A.lbu('t3', 0, 't3'); A.addu('t0', 't0', 't3')
    A.b('.sas_loop'); A.nop()
    A.label('.sas_no'); A.move('v0', 'zero'); f.ret()
    A.label('.sas_yes'); A.li('v0', 1); f.end()

    # a0=script executable, a1=full handler hash -> v0=vm executable,
    # v1=unique live owner instance. Do not guess among multiple instances.
    f = A.func('dm_script_resolve', saves=['s0', 's1', 's2', 's3', 's4'], locals_size=16)
    A.move('s0', 'a0'); A.sw('a1', 0, 'sp')
    ptr('s0', '.sr_no')
    A.lw('s1', 0x28, 's0'); ptr('s1', '.sr_no')
    A.lw('s2', 0x30, 's0'); A.sltiu('t0', 's2', 257)
    A.beqz('t0', '.sr_no'); A.nop()
    A.label('.sr_object')
    A.beqz('s2', '.sr_no'); A.nop()
    A.lw('s3', 0, 's1'); ptr('s3', '.sr_next')
    A.lw('t0', 0x24, 's3'); A.sltiu('t1', 't0', 4097)
    A.beqz('t1', '.sr_next'); A.nop()
    A.blez('t0', '.sr_next'); A.nop()
    A.lw('t0', 0x20, 's3'); ptr('t0', '.sr_next')
    A.move('a0', 's3'); A.move('a1', 'sp'); call(FIND_FUNC)
    A.bltz('v0', '.sr_next'); A.nop()
    A.lw('t0', 0x24, 's3'); A.sltu('t0', 'v0', 't0')
    A.beqz('t0', '.sr_next'); A.nop()
    A.lw('t0', 0x20, 's3'); A.sll('t1', 'v0', 2)
    A.addu('t0', 't0', 't1'); A.lw('s4', 0, 't0')
    A.move('a0', 's4'); call('dm_script_action_safe')
    A.beqz('v0', '.sr_next'); A.nop()
    A.lw('t0', 0x2C, 's3'); ptr('t0', '.sr_next')
    A.lw('v1', 0, 't0'); ptr('v1', '.sr_next')
    A.lw('t0', 0, 'v1'); A.bnez('t0', '.sr_next'); A.nop()
    A.lw('t0', 0x2C, 'v1'); A.bne('t0', 's3', '.sr_next'); A.nop()
    A.lw('t0', 0x30, 'v1'); A.andi('t0', 't0', 1)
    A.bnez('t0', '.sr_next'); A.nop()
    A.move('v0', 's4'); f.ret()
    A.label('.sr_next')
    A.addiu('s1', 's1', 4); A.addiu('s2', 's2', -1)
    A.b('.sr_object'); A.nop()
    A.label('.sr_no'); A.move('v0', 'zero'); A.move('v1', 'zero'); f.end()

    # Enumerate this executable's adjacent original display-name/handler pairs.
    f = A.func('dm_script_scan_exec', saves=['s0', 's1', 's2', 's3', 's4', 's5', 's6', 's7'])
    A.move('s0', 'a0'); ptr('s0', f.epi)
    A.lw('s1', 0x38, 's0'); ptr('s1', f.epi)
    A.lw('s2', 0x3C, 's0'); A.sltiu('t0', 's2', 8193)
    A.beqz('t0', f.epi); A.nop()
    A.addiu('s2', 's2', -1); A.addiu('s1', 's1', 4)
    A.label('.sse_loop')
    A.blez('s2', f.epi); A.nop()
    A.lw_abs('s5', 'dm_script_command_count'); A.sltiu('t0', 's5', MAX_COMMANDS)
    A.beqz('t0', f.epi); A.nop()
    A.lw('a0', 0, 's1'); call('dm_script_callback_hash')
    A.beqz('v0', '.sse_next'); A.nop()
    A.move('s3', 'v0'); A.lw('s4', -4, 's1'); ptr('s4', '.sse_next', False)
    A.move('a0', 's4'); call('dm_script_is_progression')
    A.lw_abs('t0', 'dm_script_command_kind')
    A.bne('v0', 't0', '.sse_next'); A.nop()
    A.move('a0', 's0'); A.move('a1', 's3'); call('dm_script_resolve')
    A.beqz('v0', '.sse_next'); A.nop()
    A.move('s6', 'v1'); A.move('s7', 'v0')
    A.sll('t0', 's5', 6); A.la('t1', 'dm_script_command_names')
    A.addu('t1', 't1', 't0'); A.move('t0', 's4'); A.move('s4', 't1')
    A.li('t2', NAME_SIZE - 1)
    A.label('.sse_copy')
    A.lbu('t3', 0, 't0'); A.sb('t3', 0, 't1')
    A.beqz('t3', '.sse_add'); A.nop()
    A.addiu('t0', 't0', 1); A.addiu('t1', 't1', 1); A.addiu('t2', 't2', -1)
    A.bgtz('t2', '.sse_copy'); A.nop()
    A.sb('zero', 0, 't1')
    A.label('.sse_add')
    A.move('a1', 's4'); A.li('a2', D.T_ACTION); call('dm_new_dyn')
    A.beqz('v0', f.epi); A.nop()
    A.sw('s3', D.E_ID, 'v0'); A.sw('s0', D.E_VALUE, 'v0')
    A.sw('s6', D.E_SUBMENU, 'v0'); A.sw('s7', D.E_POPULATE, 'v0')
    A.la('t0', 'h_script_command'); A.sw('t0', D.E_HANDLER, 'v0')
    A.lw_abs('a0', 'dm_script_command_menu'); A.move('a1', 'v0'); call('dm_add_entry')
    A.addiu('s5', 's5', 1); A.sw_abs('s5', 'dm_script_command_count')
    A.label('.sse_next')
    A.addiu('s1', 's1', 4); A.addiu('s2', 's2', -1)
    A.b('.sse_loop'); A.nop()
    f.end()

    for kind, name in enumerate(('script', 'progression')):
        f = A.func('p_' + name + '_commands')
        A.li('t0', kind); A.sw_abs('t0', 'dm_script_command_kind')
        A.la('a1', 'dm_' + name + '_commands_menu')
        A.sw_abs('a1', 'dm_script_command_menu')
        A.la('a2', S(name.title())); A.move('a3', 'zero'); call('dm_dyn_menu')
        call('dm_script_collect'); f.end()

    f = A.func('dm_script_collect', saves=['s0', 's1', 's2'])
    A.sw_abs('zero', 'dm_script_command_count')
    A.lw_abs('t0', EXEC_MAP); ptr('t0', f.epi)
    A.lw('s0', 4, 't0'); ptr('s0', f.epi)
    A.lw('s1', 8, 's0'); A.li('s2', 256)
    A.label('.sc_node')
    A.beq('s1', 's0', f.epi); A.nop()
    ptr('s1', f.epi)
    A.lw('a0', 0x20, 's1'); call('dm_script_scan_exec')
    A.move('a0', 's1'); call(TREE_NEXT); A.move('s1', 'v0')
    A.addiu('s2', 's2', -1); A.bgtz('s2', '.sc_node'); A.nop()
    f.end()

    # Resolve afresh through the live tree, then compare the captured instance
    # and function before passing a four-byte null menu parameter to Chuck.
    f = A.func('h_script_command', saves=['s0', 's1', 's2', 's3'], locals_size=16)
    A.move('s3', 'a0')
    A.lw_abs('t0', EXEC_MAP); ptr('t0', f.epi)
    A.lw('s0', 4, 't0'); ptr('s0', f.epi)
    A.lw('s1', 8, 's0'); A.li('s2', 256)
    A.label('.hsc_node')
    A.beq('s1', 's0', f.epi); A.nop()
    ptr('s1', f.epi)
    A.lw('t0', 0x20, 's1'); A.lw('t1', D.E_VALUE, 's3')
    A.beq('t0', 't1', '.hsc_found'); A.nop()
    A.move('a0', 's1'); call(TREE_NEXT); A.move('s1', 'v0')
    A.addiu('s2', 's2', -1); A.bgtz('s2', '.hsc_node'); A.nop()
    f.ret()
    A.label('.hsc_found')
    A.move('a0', 't0'); A.lw('a1', D.E_ID, 's3'); call('dm_script_resolve')
    A.beqz('v0', f.epi); A.nop()
    A.lw('t0', D.E_SUBMENU, 's3'); A.bne('t0', 'v1', f.epi); A.nop()
    A.lw('t0', D.E_POPULATE, 's3'); A.bne('t0', 'v0', f.epi); A.nop()
    A.move('a0', 'v1'); A.move('a1', 'v0'); A.move('a2', 'sp')
    A.sw('zero', 0, 'sp'); call(ADD_THREAD)
    A.beqz('v0', f.epi); A.nop()
    call('dm_hide'); f.end()


def emit_menus(A, S, C):
    for name in ('script', 'progression'):
        A.la('a0', 'dm_root_menu'); A.move('a1', 'zero')
        A.la('a2', S(name.title())); A.la('a3', 'p_' + name + '_commands')
        A.jal('dm_add_sub'); A.nop()


def emit_data(A, S, C):
    A.align(4); A.label('dm_script_audited_callbacks')
    for row in AUDITED_CALLBACKS:
        for value in row:
            A.word(value)
    A.label('dm_script_operand_sizes')
    # byte sizes of operands after the opcode and optional data-size word.
    A.asciiz(''.join(map(chr, (0, 4, 4, 4, 2, 2, 2, 2, 4, 4, 4, 4, 0, 0, 0, 4, 4, 4, 0, 0, 0, 0, 0))))
    A.align(4)


def emit_bss(A, C):
    for label in ('dm_script_command_count', 'dm_script_command_kind', 'dm_script_command_menu'):
        A.label(label); A.word(0)
    A.align(16); A.label('dm_script_command_names'); A.space(MAX_COMMANDS * NAME_SIZE)
