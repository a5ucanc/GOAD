import re
from pathlib import Path
from typing import List, Optional

_LINE = re.compile(r'^\s*([^#=\s][^=]*?)\s*=\s*"?(.*?)"?\s*$')


class Vmx:
    """A .vmx file edited in place: line order and comments kept, keys matched case-insensitively."""

    def __init__(self, path: Path, lines: List[str]):
        self.path = Path(path)
        self.lines = lines

    @classmethod
    def load(cls, path: Path) -> 'Vmx':
        return cls(path, Path(path).read_text(encoding='utf-8', errors='replace').splitlines())

    def _find(self, key: str) -> Optional[int]:
        wanted = key.lower()
        for index, line in enumerate(self.lines):
            match = _LINE.match(line)
            if match and match.group(1).lower() == wanted:
                return index
        return None

    def __getitem__(self, key: str) -> str:
        index = self._find(key)
        if index is None:
            raise KeyError(key)
        return _LINE.match(self.lines[index]).group(2)

    def __contains__(self, key: str) -> bool:
        return self._find(key) is not None

    def __setitem__(self, key: str, value) -> None:
        index = self._find(key)
        if index is None:
            self.lines.append(f'{key} = "{value}"')
        else:
            original = _LINE.match(self.lines[index]).group(1)
            self.lines[index] = f'{original} = "{value}"'

    def __delitem__(self, key: str) -> None:
        index = self._find(key)
        if index is not None:
            del self.lines[index]

    def save(self) -> None:
        self.path.write_text('\n'.join(self.lines) + '\n', encoding='utf-8')
