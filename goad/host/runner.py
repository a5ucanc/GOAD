import subprocess
import sys
from pathlib import Path
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

    def stream(self, argv: List[str], log_path: Path) -> int:
        """Run a long command, echoing each output line to the terminal and to log_path. Returns the exit code."""
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, 'a', encoding='utf-8') as log:
            try:
                process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           text=True, encoding='utf-8', errors='replace')
            except FileNotFoundError as e:
                log.write(f'{e}\n')
                return 127
            for line in process.stdout:
                sys.stdout.write(line)
                log.write(line)
            return process.wait()


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

    def stream(self, argv: List[str], log_path: Path) -> int:
        return self.run(argv).code
