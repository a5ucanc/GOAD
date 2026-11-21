import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Dict, List, TypeVar

from rich.console import Console

from goad import GoadError

T = TypeVar('T')
console = Console()


@dataclass
class ParallelResult:
    ok: List[str] = field(default_factory=list)
    failed: Dict[str, str] = field(default_factory=dict)

    def raise_if_failed(self, action: str) -> None:
        if self.failed:
            details = '; '.join(f'{name}: {message}' for name, message in sorted(self.failed.items()))
            raise GoadError(f'{action} failed on {details}')


def run_parallel(items: Dict[str, T], fn: Callable[[str, T], None], label: str,
                 max_workers: int = 8) -> ParallelResult:
    """Run fn(name, item) for every item at once. A failure never stops the others."""
    result = ParallelResult()

    def timed(name: str, item: T) -> float:
        start = time.monotonic()
        fn(name, item)
        return time.monotonic() - start

    pool = ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(items) or 1)))
    try:
        futures = {pool.submit(timed, name, item): name for name, item in items.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                seconds = future.result()
            except Exception as e:  # every VM's outcome is reported, whatever went wrong
                result.failed[name] = str(e) or type(e).__name__
                console.print(f'{label} {name} [red]failed[/red]: {result.failed[name]}')
            else:
                result.ok.append(name)
                console.print(f'{label} {name} [green]ok[/green] ({seconds:.0f}s)')
    except BaseException:
        # Ctrl-C: do not join workers that may sit in a 20-minute wait; goad.cli.main exits the process
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    pool.shutdown(wait=True)
    return result
