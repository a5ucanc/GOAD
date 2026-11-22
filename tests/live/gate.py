"""Release gate of the spec: limits, verdicts and the Markdown report of one gate run.

Pure code, unit-tested in tests/unit/test_gate.py; tests/live/test_release_gate.py feeds it real samples.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from goad.settings import OS_NAMES

LIMITS: Dict[str, float] = {'snapshot': 120.0, 'reset': 300.0, 'deploy': 2100.0}   # user decision 2026-11-22: 35 min (was 30)
REQUIRED: Dict[str, int] = {'snapshot': 1, 'reset': 5, 'deploy': 3}
ORDER = ('deploy', 'snapshot', 'reset')


@dataclass
class Sample:
    kind: str   # deploy | snapshot | reset | template
    seconds: float
    ok: bool
    note: str = ''   # the OS name for a template sample


@dataclass
class GateRun:
    started: str   # ISO 8601 UTC
    commit: str
    lab: str = '2domains'
    templates: List[str] = field(default_factory=list)
    samples: List[Sample] = field(default_factory=list)


@dataclass
class Verdict:
    check: str
    limit: str
    measured: str
    passed: bool


def _timed(run: GateRun, kind: str) -> Verdict:
    samples = [s for s in run.samples if s.kind == kind]
    limit = LIMITS[kind]
    if not samples:
        return Verdict(kind, f'< {limit:.0f} s', 'no samples', False)
    longest = max(s.seconds for s in samples)
    ok = all(s.ok for s in samples) and len(samples) >= REQUIRED[kind] and longest < limit
    failed = sum(not s.ok for s in samples)
    measured = f'max {longest:.0f} s, {len(samples)} samples' + (f', {failed} failed' if failed else '')
    return Verdict(kind, f'< {limit:.0f} s', measured, ok)


def _templates(run: GateRun) -> Verdict:
    good = {s.note for s in run.samples if s.kind == 'template' and s.ok}
    bad = [name for name in OS_NAMES if name not in good]
    measured = f'{len(OS_NAMES)}/{len(OS_NAMES)}' if not bad else 'failed or missing: ' + ', '.join(bad)
    return Verdict('template test', 'pass', measured, not bad)


def verdicts(run: GateRun) -> List[Verdict]:
    return [_timed(run, kind) for kind in ORDER] + [_templates(run)]


def passed(run: GateRun) -> bool:
    return all(v.passed for v in verdicts(run))


def render(run: GateRun) -> str:
    lines = [f'# Release gate: {run.lab}', '',
             f'Started: {run.started}', f'Commit: {run.commit}', f'Templates: {", ".join(run.templates) or "-"}', '',
             '| Check | Limit | Measured | Result |', '|---|---|---|---|']
    lines += [f'| {v.check} | {v.limit} | {v.measured} | {"pass" if v.passed else "fail"} |' for v in verdicts(run)]
    lines += ['', '## Samples', '']
    lines += [f'- {s.kind} {s.seconds:.0f} s {"ok" if s.ok else "FAILED"} {s.note}'.rstrip() for s in run.samples]
    lines += ['', f'Result: {"PASS" if passed(run) else "FAIL"}', '']
    return '\n'.join(lines)


def write_report(run: GateRun, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(render(run))
    os.replace(tmp, path)
