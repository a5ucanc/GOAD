import subprocess
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple


@dataclass(frozen=True)
class Result:
    code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.code == 0


class Runner:
    """Runs a program from an argv list (never through a shell)."""

    def run(self, argv: List[str], timeout: Optional[float] = None) -> Result:
        try:
            done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                                  encoding='utf-8', errors='replace')
        except FileNotFoundError as e:
            return Result(127, '', str(e))
        except subprocess.TimeoutExpired:
            return Result(124, '', f'timed out after {timeout}s: {argv[0]}')
        return Result(done.returncode, done.stdout or '', done.stderr or '')


class FakeRunner(Runner):
    """Records every argv; answers with the first matching canned result, else success with no output."""

    def __init__(self):
        self.calls: List[List[str]] = []
        self._responses: List[Tuple[Callable[[List[str]], bool], Result]] = []

    def respond(self, predicate: Callable[[List[str]], bool], result: Result) -> None:
        self._responses.append((predicate, result))

    def run(self, argv: List[str], timeout: Optional[float] = None) -> Result:
        self.calls.append(list(argv))
        for predicate, result in self._responses:
            if predicate(argv):
                return result
        return Result(0, '', '')
