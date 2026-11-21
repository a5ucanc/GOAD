import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

from rich.console import Console

from goad import GoadError, __version__

err = Console(stderr=True)


class NeedsConfirmation(GoadError):
    """A prompt was needed but stdin is not a TTY and --yes was not given."""


def confirm(question: str, yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        raise NeedsConfirmation(question)
    return input(f'{question} (y/N) ').strip().lower() in ('y', 'yes')


@dataclass
class Context:
    settings: Any
    runner: Any


def make_context() -> Context:
    from goad.host.runner import Runner
    from goad.settings import load_settings
    return Context(settings=load_settings(), runner=Runner())


def _check(args, ctx) -> int:
    from rich.table import Table

    from goad.host import checks
    results = checks.run_checks(ctx.runner, ctx.settings, need_packer=True, need_ansible=True)
    table = Table('Check', 'Status', 'Detail')
    for check in results:
        table.add_row(check.name, '[green]ok[/green]' if check.ok else '[red]fail[/red]', check.detail)
    Console().print(table)
    return 0 if all(check.ok for check in results) else 1


def _not_implemented(args, ctx) -> int:
    err.print('not implemented')
    return 1


def _store(ctx):
    from goad.templates.store import TemplateStore
    from goad.vmware.vmrun import Vmrun
    return TemplateStore(ctx.settings, Vmrun(ctx.runner, ctx.settings))


def _template_list(args, ctx) -> int:
    from rich.table import Table

    from goad.state import templates_in_use
    in_use = templates_in_use(ctx.settings)
    table = Table('Name', 'OS', 'Built', 'In use')
    for template in _store(ctx).list():
        table.add_row(template.name, template.os, template.built_at, 'yes' if template.name in in_use else '')
    Console().print(table)
    return 0


def _template_delete(args, ctx) -> int:
    _store(ctx).delete(args.name, args.yes)
    Console().print(f'template {args.name} deleted')
    return 0


def _template_build(args, ctx) -> int:
    from goad.host.awake import keep_host_awake
    from goad.templates.build import build_template
    with keep_host_awake():
        template = build_template(args.os, ctx.settings, ctx.runner, _store(ctx))
    Console().print(f'template {template.name} built')
    return 0


def _template_test(args, ctx) -> int:
    from goad.host.awake import keep_host_awake
    from goad.templates.smoke import smoke_test
    with keep_host_awake():
        smoke_test(args.os, ctx.settings, ctx.runner, _store(ctx))
    return 0


def _open(ctx, need_definition: bool = True):
    """Open the deployed lab; need_definition=False skips the working lab.yml, so an edited copy cannot block."""
    from goad.lab.context import open_lab
    return open_lab(ctx.settings, ctx.runner, need_definition=need_definition)


def _lab_deploy(args, ctx) -> int:
    from goad.host.awake import keep_host_awake
    from goad.lab.deploy import deploy
    with keep_host_awake():
        deploy(args.lab, ctx.settings, ctx.runner, _store(ctx), ip_range=args.range)
    return 0


def _lab_status(args, ctx) -> int:
    from rich.table import Table

    from goad.lab import lifecycle
    lab = _open(ctx, need_definition=False)
    state = lab.state
    console = Console()
    console.print(f'lab {state.lab} ({state.ip_range}.0/24), snapshot {state.current or "-"}, '
                  f'deploy step {state.step or "-"}')
    table = Table('Host', 'Hostname', 'IP', 'Template', 'Power')
    for row in lifecycle.status(lab):
        table.add_row(row.host, row.hostname, row.ip, row.template, row.power)
    console.print(table)
    return 0


def _lab_start(args, ctx) -> int:
    from goad.lab.power import start_all, wait_ready
    lab = _open(ctx, need_definition=False)
    start_all(lab.vmrun, lab.vms())
    wait_ready(lab.endpoints())
    return 0


def _lab_stop(args, ctx) -> int:
    from goad.lab.power import stop_all
    lab = _open(ctx, need_definition=False)
    stop_all(lab.vmrun, lab.vms())
    return 0


def _lab_provision(args, ctx) -> int:
    from goad.host.awake import keep_host_awake
    from goad.lab import provision as provisioning
    lab = _open(ctx)
    if not provisioning.PLAYBOOK.exists():
        raise GoadError('no Ansible playbooks yet (ansible/site.yml)')
    tags = args.tags.split(',') if args.tags else None
    started = time.monotonic()
    with keep_host_awake():
        provisioning.provision(ctx.settings, ctx.runner, lab.definition, lab.state, tags=tags)
    print(f'provisioned in {int(time.monotonic() - started)} s')
    return 0


def _lab_reset(args, ctx) -> int:
    from goad.host.awake import keep_host_awake
    from goad.lab import snapshots
    from goad.lab.context import open_lab
    from goad.state import load_state
    state = load_state(ctx.settings)
    if state is None:
        raise GoadError('no lab deployed: run goad lab deploy <lab>')
    record = state.snapshot(args.snapshot)
    if record is None:
        raise GoadError(f'unknown snapshot {args.snapshot}')
    lab = open_lab(ctx.settings, ctx.runner, lab_yml=record.lab_yml)
    with keep_host_awake():
        snapshots.reset(lab, args.snapshot)
    return 0


def _lab_destroy(args, ctx) -> int:
    from goad.lab import lifecycle
    lifecycle.destroy(ctx.settings, ctx.runner, args.yes)
    Console().print('lab destroyed')
    return 0


def _snapshot_take(args, ctx) -> int:
    from goad.host.awake import keep_host_awake
    from goad.lab import snapshots
    lab = _open(ctx)
    with keep_host_awake():
        snapshots.take(lab, args.label)
    return 0


def _snapshot_list(args, ctx) -> int:
    from rich.table import Table

    from goad.lab import snapshots
    table = Table('Name', 'Taken', 'Label', 'Missing on')
    for row in snapshots.list_snapshots(_open(ctx, need_definition=False)):
        table.add_row(row.record.name, row.record.taken_at, row.record.label, ', '.join(row.missing_on))
    Console().print(table)
    return 0


def _snapshot_delete(args, ctx) -> int:
    from goad.lab import snapshots
    lab = _open(ctx, need_definition=False)
    if not confirm(f'Delete snapshot {args.name}?', args.yes):
        raise GoadError('cancelled')
    snapshots.delete(lab, args.name)
    Console().print(f'snapshot {args.name} deleted')
    return 0


def _creds(args, ctx) -> int:
    from rich.table import Table

    from goad.lab import lifecycle
    table = Table('Account', 'Password', 'Scope')
    for row in lifecycle.creds(_open(ctx)):
        table.add_row(row.account, row.password, row.scope)
    Console().print(table)
    return 0


def _vm_start(args, ctx) -> int:
    from goad.lab import lifecycle
    lifecycle.vm_start(_open(ctx, need_definition=False), args.vm)
    return 0


def _vm_stop(args, ctx) -> int:
    from goad.lab import lifecycle
    lifecycle.vm_stop(_open(ctx, need_definition=False), args.vm, hard=args.hard)
    return 0


def _vm_console(args, ctx) -> int:
    from goad.lab import lifecycle
    lifecycle.vm_console(_open(ctx, need_definition=False), args.vm)
    return 0


# command path -> handler(args, ctx) -> exit code
HANDLERS: Dict[Tuple[str, ...], Callable[[argparse.Namespace, Context], int]] = {
    ('check',): _check,
    ('template', 'build'): _template_build,
    ('template', 'list'): _template_list,
    ('template', 'delete'): _template_delete,
    ('template', 'test'): _template_test,
    ('lab', 'deploy'): _lab_deploy,
    ('lab', 'status'): _lab_status,
    ('lab', 'start'): _lab_start,
    ('lab', 'stop'): _lab_stop,
    ('lab', 'provision'): _lab_provision,
    ('lab', 'reset'): _lab_reset,
    ('lab', 'destroy'): _lab_destroy,
    ('snapshot', 'take'): _snapshot_take,
    ('snapshot', 'list'): _snapshot_list,
    ('snapshot', 'delete'): _snapshot_delete,
    ('creds',): _creds,
    ('vm', 'start'): _vm_start,
    ('vm', 'stop'): _vm_stop,
    ('vm', 'console'): _vm_console,
}

OS_CHOICES = ('win2022', 'win2025', 'win11', 'ubuntu2404')


def _ip_range(value: str) -> str:
    if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}$', value):
        raise argparse.ArgumentTypeError(f'{value!r} is not A.B.C')
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='goad', description='Deploy and maintain one Active Directory lab on VMware Workstation.')
    parser.add_argument('--version', action='version', version=f'goad {__version__}')
    groups = parser.add_subparsers(dest='group', required=True, metavar='{check,template,lab,snapshot,creds,vm}')

    check = groups.add_parser('check', help='check the host: VMware, Packer, lab network, disk, CA certificates')
    check.set_defaults(command=('check',))

    template = groups.add_parser('template', help='build, list, test and delete VM templates')
    actions = template.add_subparsers(dest='action', required=True)
    build = actions.add_parser('build', help='build a new template version with Packer')
    build.add_argument('os', choices=OS_CHOICES)
    build.set_defaults(command=('template', 'build'))
    listing = actions.add_parser('list', help='list built templates')
    listing.set_defaults(command=('template', 'list'))
    delete = actions.add_parser('delete', help='delete a template version')
    delete.add_argument('name')
    delete.add_argument('--yes', action='store_true', help='do not ask for confirmation')
    delete.set_defaults(command=('template', 'delete'))
    test = actions.add_parser('test', help='clone the latest template, first-boot it, check it, delete it')
    test.add_argument('os', choices=OS_CHOICES)
    test.set_defaults(command=('template', 'test'))

    from goad.lab.definition import LAB_NAMES
    lab = groups.add_parser('lab', help='deploy, start, stop, provision, reset and destroy the lab')
    lab_actions = lab.add_subparsers(dest='action', required=True)
    deploy = lab_actions.add_parser('deploy', help='deploy a lab; run again to resume an interrupted deploy')
    deploy.add_argument('lab', choices=LAB_NAMES)
    deploy.add_argument('--range', type=_ip_range, help='first three octets of the lab network, e.g. 192.168.56')
    deploy.set_defaults(command=('lab', 'deploy'))
    lab_actions.add_parser('status', help='show the lab and its VMs').set_defaults(command=('lab', 'status'))
    lab_actions.add_parser('start', help='start all VMs and wait until ready').set_defaults(command=('lab', 'start'))
    lab_actions.add_parser('stop', help='stop all VMs').set_defaults(command=('lab', 'stop'))
    provision = lab_actions.add_parser('provision', help='run the Ansible playbook against the lab')
    provision.add_argument('--tags', help='comma-separated Ansible tags')
    provision.set_defaults(command=('lab', 'provision'))
    reset = lab_actions.add_parser('reset', help='revert every VM and lab.yml to a snapshot')
    reset.add_argument('snapshot', nargs='?', default='base')
    reset.set_defaults(command=('lab', 'reset'))
    destroy = lab_actions.add_parser('destroy', help='delete all VMs and the lab state')
    destroy.add_argument('--yes', action='store_true', help='do not ask for confirmation')
    destroy.set_defaults(command=('lab', 'destroy'))

    snapshot = groups.add_parser('snapshot', help='take, list and delete whole-lab snapshots')
    snap_actions = snapshot.add_subparsers(dest='action', required=True)
    take = snap_actions.add_parser('take', help='snapshot every VM (briefly powers the lab off)')
    take.add_argument('label', nargs='?')
    take.set_defaults(command=('snapshot', 'take'))
    snap_actions.add_parser('list', help='list snapshots').set_defaults(command=('snapshot', 'list'))
    snap_delete = snap_actions.add_parser('delete', help='delete a snapshot')
    snap_delete.add_argument('name')
    snap_delete.add_argument('--yes', action='store_true', help='do not ask for confirmation')
    snap_delete.set_defaults(command=('snapshot', 'delete'))

    groups.add_parser('creds', help='show lab accounts and passwords').set_defaults(command=('creds',))

    vm = groups.add_parser('vm', help='start, stop or open the console of one VM')
    vm_actions = vm.add_subparsers(dest='action', required=True)
    vm_start = vm_actions.add_parser('start', help='start one VM')
    vm_start.add_argument('vm')
    vm_start.set_defaults(command=('vm', 'start'))
    vm_stop = vm_actions.add_parser('stop', help='stop one VM')
    vm_stop.add_argument('vm')
    vm_stop.add_argument('--hard', action='store_true', help='power off without a guest shutdown')
    vm_stop.set_defaults(command=('vm', 'stop'))
    vm_console = vm_actions.add_parser('console', help='open the VMware console of one VM')
    vm_console.add_argument('vm')
    vm_console.set_defaults(command=('vm', 'console'))
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return HANDLERS[args.command](args, make_context())
    except NeedsConfirmation as e:
        err.print(f'{e}\nconfirmation needed: re-run with --yes')
        return 2
    except GoadError as e:
        err.print(f'[red]error:[/red] {e}')
        return 1
    except KeyboardInterrupt:
        # worker threads may be blocked in vmrun or a wait: os._exit stops them; saved steps survive
        print('interrupted: run the same command again to resume', file=sys.stderr)
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(130)
