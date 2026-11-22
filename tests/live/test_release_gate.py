"""Run by hand on the VMware host with all four templates built, 16 GB of free RAM and no lab deployed:
pytest -m live -k gate -s. It takes 3 to 4 hours.

The release gate of the spec on 2domains: goad template test for every template, 3 deploys in a row,
a snapshot after each, 5 resets in a row to base on the first deploy. Every command must succeed on its
first call. The report (~/.goad/logs/release-gate-<stamp>.md) is rewritten after every sample.
"""
import subprocess
import time
from datetime import datetime, timezone
from typing import Callable, List

import pytest

from goad.cli import main
from goad.host.awake import keep_host_awake
from goad.host.paths import to_wsl
from goad.host.runner import Runner
from goad.lab.context import vm_folder
from goad.settings import OS_NAMES, load_settings
from goad.state import load_state, log_dir, working_lab_path
from tests.live.gate import GateRun, Sample, passed, render, write_report
from tests.live.helpers import add_marker, marker_exists, wait_healthy

pytestmark = pytest.mark.live

LAB = '2domains'
DEPLOYS = 3
RESETS = 5


def _commit() -> str:
    return subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()


def test_release_gate():
    settings, runner = load_settings(), Runner()
    if load_state(settings) is not None:
        pytest.fail('a lab is already deployed: run goad lab destroy first')
    now = datetime.now(timezone.utc)
    run = GateRun(started=now.strftime('%Y-%m-%dT%H:%M:%SZ'), commit=_commit(), lab=LAB)
    report = log_dir(settings) / f'release-gate-{now.strftime("%Y%m%d-%H%M%S")}.md'

    def record(sample: Sample) -> None:
        run.samples.append(sample)
        write_report(run, report)

    def timed(kind: str, note: str, argv: List[str]) -> bool:
        start = time.monotonic()
        try:
            code = main(argv)
            failure = f'{note}: exit {code}'
        except Exception as e:  # main turns GoadError into an exit code; anything else is a failure too
            code, failure = 1, f'{note}: {type(e).__name__}: {e}'
        ok = code == 0
        record(Sample(kind, time.monotonic() - start, ok, note if ok else failure))
        return ok

    def check(kind: str, note: str, fn: Callable[[], None]) -> bool:
        """Run a health or correctness check after a step; a failure is a failed sample of that step."""
        try:
            fn()
        except Exception as e:  # AssertionError from the checks, or a PSRP failure
            record(Sample(kind, 0.0, False, f'{note}: {e}'))
            return False
        return True

    def healthy() -> None:
        wait_healthy(settings, runner)

    def deploy_finished() -> None:
        state = load_state(settings)
        assert state is not None and state.step == 'finish', f'deploy step {state.step if state else None}'
        if not run.templates:
            run.templates = list(state.templates)

    def reset_checks(marker: str) -> Callable[[], None]:
        def checks() -> None:
            healthy()
            state = load_state(settings)
            assert not marker_exists(state.hosts['dc01'].ip, marker), f'{marker} still in AD after reset'
            assert working_lab_path(settings).read_text() == state.snapshot('base').lab_yml, \
                'working lab.yml differs from the base snapshot copy'
            assert state.current == 'base', f'current snapshot {state.current}'
        return checks

    def edit_before_reset(marker: str, n: int) -> None:
        add_marker(load_state(settings).hosts['dc01'].ip, marker)
        path = working_lab_path(settings)
        path.write_text(path.read_text() + f'# gate edit {n}\n')

    def destroyed(hosts: List[str]) -> None:
        assert load_state(settings) is None, 'lab state left after destroy'
        left = [host for host in hosts if to_wsl(vm_folder(settings, host)).exists()]
        assert not left, f'VM folders left after destroy: {", ".join(left)}'

    def lab_part() -> None:
        for i in range(1, DEPLOYS + 1):
            note = f'deploy {i}/{DEPLOYS}'
            if not timed('deploy', note, ['lab', 'deploy', LAB]):
                return
            if not check('deploy', note, deploy_finished) or not check('deploy', note, healthy):
                return
            hosts = list(load_state(settings).hosts)
            note = f'snapshot {i}/{DEPLOYS}'
            if not timed('snapshot', note, ['snapshot', 'take', f'gate-{i}']) or not check('snapshot', note, healthy):
                return
            if i == 1:
                for n in range(1, RESETS + 1):
                    note, marker = f'reset {n}/{RESETS}', f'gate-marker-{n}'
                    if not check('reset', f'{note} setup', lambda: edit_before_reset(marker, n)):
                        return
                    if not timed('reset', note, ['lab', 'reset']) or not check('reset', note, reset_checks(marker)):
                        return
            if main(['lab', 'destroy', '--yes']) != 0:
                record(Sample('deploy', 0.0, False, f'destroy {i}/{DEPLOYS}: exit non-zero'))
                return
            if not check('deploy', f'destroy {i}/{DEPLOYS}', lambda: destroyed(hosts)):
                return

    write_report(run, report)
    try:
        with keep_host_awake():
            for os_name in OS_NAMES:
                timed('template', os_name, ['template', 'test', os_name])
            lab_part()
    finally:
        if load_state(settings) is not None:
            main(['lab', 'destroy', '--yes'])   # best effort: the gate result is what is reported
        write_report(run, report)
        print(f'\nrelease gate report: {report}')
    assert passed(run), render(run)
