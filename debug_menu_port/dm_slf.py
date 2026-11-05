"""Optional reporting for the retail VM's existing ten-second SLF recall timer.

The native call/reset behavior is retained. The sole call site is redirected
through a wrapper; disabled reporting tail-calls the original function.
"""
MENUS = ()
DYNAMIC_MENUS = ()
CALL_SITE = 0x2F659C
NATIVE_CALL = 0x2F766C
GET_TIME_INC = 0x2F567C
KPRINTF = 0x609508
THREAD_LAST_PC, THREAD_TIMER = 0x1B0, 0x1B4


def emit_code(A, S, C):
    def call(target):
        A.jal(target); A.nop()

    A.label('hook_slf_call')
    A.lw_abs('t0', 'dm_report_slf_recall_timeouts')
    A.bnez('t0', '.slf_reporting_enabled'); A.nop()
    A.j(NATIVE_CALL); A.nop()
    A.label('.slf_reporting_enabled')
    f = A.func('dm_slf_report_call', saves=['s0', 's1', 's2', 's3'], fsaves=['f20'])
    A.move('s0', 'a0'); A.move('s1', 'a2')
    A.lw('s2', THREAD_LAST_PC, 's0'); A.lwc1('f20', THREAD_TIMER, 's0')
    call(NATIVE_CALL)
    A.move('s3', 'v0')
    A.bnez('s3', '.slf_return'); A.nop()  # SLF completed, not a recall.
    A.bne('s2', 's1', '.slf_return'); A.nop()  # First frame at a different SLF.
    A.lw('t0', THREAD_TIMER, 's0')
    A.bnez('t0', '.slf_return'); A.nop()  # Native timer has not expired/reset.
    call(GET_TIME_INC)
    A.add_s('f0', 'f20', 'f0'); A.li_f('f1', 10.0)
    A.c_lt_s('f1', 'f0'); A.nop()
    A.bc1f('.slf_return'); A.nop()
    A.la('a0', S('SLF recall timeout: thread=0x%08x PC=0x%08x (over 10 seconds)\n'))
    A.move('a1', 's0'); A.move('a2', 's1'); call(KPRINTF)
    A.lw_abs('t0', 'dm_slf_report_count'); A.addiu('t0', 't0', 1)
    A.sw_abs('t0', 'dm_slf_report_count')
    A.label('.slf_return'); A.move('v0', 's3')
    f.end()
    A.label('dm_slf_code_end')


def emit_menus(A, S, C):
    pass


def emit_data(A, S, C):
    pass


def emit_bss(A, C):
    A.align(4)
    A.label('dm_report_slf_recall_timeouts'); A.word(0)
    A.label('dm_slf_report_count'); A.word(0)
