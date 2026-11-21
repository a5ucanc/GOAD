import datetime
import os
from pathlib import Path
from typing import Callable, Optional

from rich.console import Console

from goad import GoadError
from goad.host.checks import run_checks
from goad.host.paths import to_windows
from goad.host.runner import Runner
from goad.settings import OS_NAMES, Settings, resolve_packer
from goad.templates.iso import ensure_iso
from goad.templates.store import BUILD_DIR, OS_FAMILY, Template, TemplateStore

REPO = Path(__file__).resolve().parents[2]
PASSWORD = 'Aa1234567890!'
console = Console()


def packer_env(settings: Settings) -> dict:
    """Packer's ISO/plugin download cache sits beside the templates, not in the repo.
    WSLENV forwards the variable to the Windows process (/w: no path translation)."""
    cache = settings.template_root.rsplit('\\', 1)[0] + '\\cache'
    forwarded = [v for v in os.environ.get('WSLENV', '').split(':') if v and not v.startswith('PACKER_CACHE_DIR')]
    return {'PACKER_CACHE_DIR': cache, 'WSLENV': ':'.join(forwarded + ['PACKER_CACHE_DIR/w'])}


def packer_dir(os_name: str) -> Path:
    return REPO / 'packer' / ('windows' if OS_FAMILY[os_name] == 'windows' else 'ubuntu')


def _packer_sha(runner: Runner) -> str:
    result = runner.run(['git', '-C', str(REPO), 'rev-parse', 'HEAD:packer'], timeout=30)
    return result.stdout.strip() if result.ok else 'unknown'


def build_template(os_name: str, settings: Settings, runner: Runner, store: TemplateStore,
                   checks: Callable = run_checks,
                   packer_path: Callable[[str], Optional[str]] = resolve_packer) -> Template:
    if os_name not in OS_NAMES:
        raise GoadError(f'unknown OS {os_name}: pick one of {", ".join(OS_NAMES)}')
    failed = [c for c in checks(runner, settings, need_packer=True) if not c.ok]
    if failed:
        raise GoadError('host checks failed: ' + '; '.join(f'{c.name}: {c.detail}' for c in failed))
    packer = packer_path(settings.packer)

    version = store.next_version(os_name)
    name = f'{os_name}-v{version}'
    out_dir = f'{settings.template_root}\\{BUILD_DIR}\\{name}'
    source = packer_dir(os_name)
    log = settings.state_dir / 'logs' / f'template-{name}.log'
    iso_url, iso_checksum = ensure_iso(os_name, settings, runner)
    variables = {
        'iso_url': iso_url,
        'iso_checksum': iso_checksum,
        'output_directory': out_dir,
        'vm_name': name,
        'password': PASSWORD,
        'ca_dir': settings.ca_certs_dir or '',
    }

    console.print(f'building template {name} (log: {log})')
    env = packer_env(settings)
    if runner.stream([packer, 'init', to_windows(source)], log, env) != 0:
        raise GoadError(f'packer init failed: see {log}')
    argv = [packer, 'build', '-force', f'-var-file={to_windows(source / f"{os_name}.pkrvars.hcl")}']
    for key, value in variables.items():
        argv += ['-var', f'{key}={value}']
    argv.append(to_windows(source))
    if runner.stream(argv, log, env) != 0:
        raise GoadError(f'packer build of {name} failed: see {log}')

    built = store.root / BUILD_DIR / name
    final = store.root / name
    built.rename(final)
    store.vmrun.snapshot(store.windows_vmx(name), 'base')
    template = Template(name=name, os=os_name, version=version, vmx=store.windows_vmx(name),
                        built_at=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                        packer_sha=_packer_sha(runner))
    # template.json last: its presence marks a finished template
    template.write(final)
    return template
