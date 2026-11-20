import argparse
import sys
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
    results = checks.run_checks(ctx.runner, ctx.settings, need_packer=True)
    table = Table('Check', 'Status', 'Detail')
    for check in results:
        table.add_row(check.name, '[green]ok[/green]' if check.ok else '[red]fail[/red]', check.detail)
    Console().print(table)
    return 0 if all(check.ok for check in results) else 1


def _not_implemented(args, ctx) -> int:
    err.print('not implemented')
    return 1


# command path -> handler(args, ctx) -> exit code
HANDLERS: Dict[Tuple[str, ...], Callable[[argparse.Namespace, Context], int]] = {
    ('check',): _check,
    ('template', 'build'): _not_implemented,
    ('template', 'list'): _not_implemented,
    ('template', 'delete'): _not_implemented,
    ('template', 'test'): _not_implemented,
}

OS_CHOICES = ('win2022', 'win2025', 'win11', 'ubuntu2404')


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='goad', description='Deploy and maintain one Active Directory lab on VMware Workstation.')
    parser.add_argument('--version', action='version', version=f'goad {__version__}')
    groups = parser.add_subparsers(dest='group', required=True, metavar='{check,template}')

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
