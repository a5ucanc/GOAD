from dataclasses import dataclass, field, fields
from typing import List


@dataclass
class SnapshotRecord:
    """goad's view of the lab when a named whole-lab snapshot was taken."""
    name: str
    # "<scenario>@<target>" or "extension:<name>"
    taken_for: str
    # asdict(EnabledScenario) of every entry enabled at snapshot time
    scenarios: List[dict] = field(default_factory=list)
    vagrant_disabled: bool = False
    extensions: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data):
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})
