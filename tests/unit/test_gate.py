from tests.live.gate import GateRun, Sample, passed, render, verdicts

OK_TEMPLATES = [Sample('template', 300.0, True, os) for os in ('win2022', 'win2025', 'win11', 'ubuntu2404')]


def run(*samples):
    return GateRun(started='2026-11-22T10:00:00Z', commit='abc1234', templates=['win2022-v1', 'win2025-v1'],
                   samples=list(samples))


def good():
    return run(*[Sample('deploy', 1500.0, True)] * 3, *[Sample('snapshot', 90.0, True)] * 3,
               *[Sample('reset', 200.0, True)] * 5, *OK_TEMPLATES)


def by_check(r):
    return {v.check: v for v in verdicts(r)}


def test_all_within_limits_passes():
    assert passed(good())
    assert [v.check for v in verdicts(good())] == ['deploy', 'snapshot', 'reset', 'template test']


def test_limit_is_strict():
    r = good()
    r.samples.append(Sample('reset', 300.0, True))
    assert not by_check(r)['reset'].passed
    assert not passed(r)


def test_too_few_resets_fails():
    r = run(*[Sample('deploy', 1500.0, True)] * 3, Sample('snapshot', 90.0, True),
            *[Sample('reset', 200.0, True)] * 4, *OK_TEMPLATES)
    assert not by_check(r)['reset'].passed
    assert by_check(r)['deploy'].passed


def test_failed_sample_breaks_the_row():
    r = good()
    r.samples.append(Sample('deploy', 400.0, False, 'deploy 4/3: exit 1'))
    assert not by_check(r)['deploy'].passed


def test_missing_template_fails_and_is_named():
    r = run(*good().samples[:11], *OK_TEMPLATES[:3])
    v = by_check(r)['template test']
    assert not v.passed and 'ubuntu2404' in v.measured


def test_measured_text():
    assert by_check(good())['reset'].measured == 'max 200 s, 5 samples'


def test_render_has_header_table_samples_and_verdict():
    text = render(good())
    assert 'abc1234' in text and '2domains' in text and 'win2025-v1' in text
    assert '| deploy | < 2100 s | max 1500 s, 3 samples | pass |' in text
    assert 'Result: PASS' in text
    bad = good()
    bad.samples.append(Sample('snapshot', 130.0, True))
    assert 'Result: FAIL' in render(bad)


def test_deploy_limit_is_35_minutes():
    # User decision 2026-11-22: 30 minutes became 35 after the measured 1802-1900 s deploys.
    r = good()
    r.samples.append(Sample('deploy', 2050.0, True))
    assert by_check(r)['deploy'].passed
    r.samples.append(Sample('deploy', 2100.0, True))
    assert not by_check(r)['deploy'].passed
