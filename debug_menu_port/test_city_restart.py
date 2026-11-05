"""City relaunch arguments, preflight safety and exact native teardown order."""
import dm_build as D
import dm_restart as X
from emu import Mem, CPU, c_format


class Restarted(Exception): pass
class Exited(Exception): pass


def fixture(path='cdrom0:\\SLES_536.72;1', mode=2, hero='venom'):
    A, blob = D.build()
    mem = Mem(); mem.write(D.BASE, blob)
    mem.write(0x01000000, bytes(0x10000)); mem.write(0x01E00000, bytes(0x100000))
    cpu = CPU(mem, D.BASE, A.labels['dm_end'])
    game, settings, entry, scene, app = 0x01000000, 0x01001000, 0x01002000, 0x01002100, 0x01002200
    mem.w32(D.G['g_game_ptr'], game); mem.w32(game + D.GAME_SETTINGS, settings)
    mem.write(settings + 0x8A8, hero.encode() + b'\0')
    mem.write(scene, b'CITY_ARENA\0'); mem.w32(entry + D.E_ID, scene)
    mem.write(app, path.encode() + b'\0'); mem.w32(X.APP_NAME, app); mem.w32(X.BOOT_MODE, mode)
    mem.w32(X.KERNEL_ARGS, 0x80078000); mem.w32(X.SOUND_SLOTS, 0x01003000); mem.w32(X.PACKER, 0)
    mem.w32(A.labels['dm_active_menu'], A.labels['dm_root_menu'])
    mem.w32(A.labels['dm_has_focus'], 1); mem.w32(A.labels['dm_physics_state_on_exit'], 1)
    mem.w32(A.labels['dm_replay_valid'], 1)
    log = []
    state = dict(pack=True, open=7, close=0, scrub=False, exec_returns=False)
    def string_hash(c): mem.w32(c.r[4], 0x1234)
    def pack(c): c.r[2] = int(state['pack'])
    def snprintf(c):
        result = c_format(mem.cstr(c.r[6]), c.r[7:12], mem).encode()
        mem.write(c.r[4], result[:c.r[5] - 1] + b'\0'); c.r[2] = len(result)
    def open_file(c):
        log.append(('open', mem.cstr(c.r[4]), c.r[5], c.r[6])); c.r[2] = state['open']
    def close_file(c): log.append(('close', c.r[4])); c.r[2] = state['close']
    def physics(c): log.append(('physics', c.r[4], c.r[5]))
    def cleanup(address, args):
        def invoke(c):
            assert tuple(c.r[4:4 + len(args)]) == args
            log.append(('cleanup', address))
            if state['scrub']:
                mem.write(scene, b'unloaded_scene\0'); mem.write(app, b'unloaded_boot\0')
                mem.write(settings + 0x8A8, b'unloaded_hero\0')
        return invoke
    def execute(c):
        assert c.r[5] == 5
        args = [mem.cstr(mem.u32(c.r[6] + 4 * i)) for i in range(5)]
        assert mem.u32(c.r[6] + 20) == 0
        log.append(('exec', mem.cstr(c.r[4]), args))
        assert mem.u32(A.labels['dm_active_menu']) == 0
        assert mem.u32(A.labels['dm_replay_valid']) == 0
        if state['exec_returns']: c.r[2] = 0xFFFFFFFF
        else: raise Restarted
    def exit_game(c):
        assert c.r[4] == 1; log.append(('exit', 1)); raise Exited
    cpu.stubs.update({D.G['string_hash_init']: string_hash, D.G['get_pack_file_stats']: pack,
                      D.G['snprintf']: snprintf, D.G['enable_physics']: physics,
                      X.OPEN: open_file, X.CLOSE: close_file, X.LOAD_EXEC: execute,
                      X.EXIT: exit_game, X.KPRINTF: lambda c: log.append(('fatal', mem.cstr(c.r[4])))})
    for address, args in X.CLEANUP: cpu.stubs[address] = cleanup(address, args)
    def call(name): return cpu.call(A.labels[name], args=(entry,))
    return A, mem, cpu, state, log, call, (game, settings, entry, scene, app)


def run():
    steps = 0
    for path, mode, expected in (
        ('cdrom0:\\SLES_536.72;1', 2, 'cdrom0:\\SLES_536.72;1'),
        ('cdrom0:\\SLES_536.72', 2, 'cdrom0:\\SLES_536.72;1'),
        ('SLES_536.72', 2, 'cdrom0:SLES_536.72;1'),
        ('host0:debug/SLES_536.72', 0, 'host0:debug/SLES_536.72'),
        ('host:debug/SLES_536.72', 2, 'host:debug/SLES_536.72'),
        ('debug/SLES_536.72', 0, 'host0:debug/SLES_536.72'),
    ):
        A, mem, cpu, state, log, call, objects = fixture(path, mode)
        state['scrub'] = True
        try: call('h_city_restart')
        except Restarted: pass
        else: raise AssertionError('Expected nonreturning relaunch')
        assert log[0] == ('open', expected, 1, 0) and log[1] == ('close', 7)
        assert [row[1] for row in log if row[0] == 'cleanup'] == [address for address, _ in X.CLEANUP]
        assert log[-1] == ('exec', expected, ['skip_to_loading', 'scene', 'CITY_ARENA', 'hero', 'venom'])
        assert not any(row[0] in ('exit', 'fatal') for row in log)
        steps += cpu.steps

    # Failures leave the existing game/menu intact and never begin teardown.
    for failure in ('hero_busy', 'missing_game', 'missing_hero', 'unterminated_hero', 'missing_path',
                    'unterminated_path', 'oversize_path', 'pack', 'kernel', 'audio', 'open', 'close'):
        A, mem, cpu, state, log, call, (game, settings, entry, scene, app) = fixture()
        if failure == 'hero_busy': mem.w32(A.labels['dm_hero_status'], 2)
        elif failure == 'missing_game': mem.w32(D.G['g_game_ptr'], 0)
        elif failure == 'missing_hero': mem.w32(game + D.GAME_SETTINGS, 0)
        elif failure == 'unterminated_hero': mem.write(settings + 0x8A8, b'X' * 32)
        elif failure == 'missing_path': mem.w32(X.APP_NAME, 0)
        elif failure == 'unterminated_path': mem.write(app, b'X' * X.PATH_CAPACITY)
        elif failure == 'oversize_path': mem.write(app, b'X' * 254 + b'\0')
        elif failure == 'pack': state['pack'] = False
        elif failure == 'kernel': mem.w32(X.KERNEL_ARGS, 0)
        elif failure == 'audio': mem.w32(X.SOUND_SLOTS, 0)
        else: state[failure] = -1
        call('h_city_restart')
        assert mem.u32(A.labels['dm_active_menu']) == A.labels['dm_root_menu'], failure
        assert mem.u32(A.labels['dm_city_restart_error']), failure
        assert not any(row[0] in ('cleanup', 'exec', 'exit', 'physics') for row in log), (failure, log)
        steps += cpu.steps

    # A failed LoadExec must not return to dismantled sound/render/input state.
    A, mem, cpu, state, log, call, _ = fixture(hero='ultimate_spiderman')
    state['exec_returns'] = True
    try: call('h_city_restart')
    except Exited: pass
    else: raise AssertionError('Expected terminal Exit after failed LoadExec')
    assert log[-1] == ('exit', 1) and log[-2][0] == 'fatal'
    assert log[-3][2][-1] == 'ultimate_spiderman'
    steps += cpu.steps
    print('City restart arguments, boot paths, teardown and preflight checks passed:', steps, 'steps')


if __name__ == '__main__': run()
