from goad.host import awake


class FakeProcess:
    def __init__(self, argv):
        self.argv = argv
        self.terminated = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0


def test_keeps_host_awake_while_inside(monkeypatch):
    started = []
    monkeypatch.setattr(awake, '_spawn', lambda argv: started.append(FakeProcess(argv)) or started[-1])
    with awake.keep_host_awake():
        assert len(started) == 1 and not started[0].terminated
        script = ' '.join(started[0].argv)
        assert started[0].argv[0] == 'powershell.exe' and 'SetThreadExecutionState' in script
    assert started[0].terminated


def test_released_on_error(monkeypatch):
    started = []
    monkeypatch.setattr(awake, '_spawn', lambda argv: started.append(FakeProcess(argv)) or started[-1])
    try:
        with awake.keep_host_awake():
            raise RuntimeError('build failed')
    except RuntimeError:
        pass
    assert started[0].terminated


def test_missing_powershell_does_not_block(monkeypatch):
    def boom(argv):
        raise FileNotFoundError('powershell.exe')
    monkeypatch.setattr(awake, '_spawn', boom)
    with awake.keep_host_awake():
        pass
