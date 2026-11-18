from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from goad.scenario import Scenario, Scenarios


class ScenarioRefused(Exception):

    def __init__(self, reasons):
        self.reasons = list(reasons)
        super().__init__('; '.join(self.reasons))


@dataclass
class EnabledScenario:
    name: str
    target: str
    enabled_at: str
    status: str = "enabled"

    @property
    def key(self) -> str:
        return f"{self.name}@{self.target}"


class ScenarioResolver:

    def __init__(self, scenarios: Scenarios, lab_name: str,
                 capabilities: Optional[Dict[str, List[str]]], root_dc: str, dcs: List[str],
                 host_domains: Optional[Dict[str, str]] = None):
        self.scenarios = scenarios
        self.lab_name = lab_name
        self.capabilities = capabilities
        self.root_dc = root_dc
        self.dcs = dcs
        self.host_domains = host_domains

    def domain_of(self, host: str) -> str:
        # without a host-to-domain map every host shares one domain
        if self.host_domains is None:
            return ""
        return self.host_domains.get(host, "")

    def resolve_target(self, scenario: Scenario, host: Optional[str]) -> str:
        if scenario.target:
            hosts = (self.capabilities or {}).get(scenario.target)
            if not hosts:
                raise ScenarioRefused([f"missing capability {scenario.target}"])
            if host is None:
                return hosts[0]
            if host not in hosts:
                raise ScenarioRefused([f"host {host} does not provide {scenario.target}"])
            return host
        if host is None:
            return self.root_dc
        if host not in self.dcs:
            raise ScenarioRefused([f"host {host} is not a domain controller"])
        return host

    def check_enable(self, name: str, host: Optional[str], enabled: List[EnabledScenario]) -> str:
        if self.capabilities is None:
            raise ScenarioRefused([f"lab {self.lab_name} does not support scenarios"])
        scenario = self.scenarios.get(name)
        if scenario is None:
            raise ScenarioRefused([f"unknown scenario {name}"])
        reasons = []
        if not scenario.allowed_on_lab(self.lab_name):
            reasons.append(f"not available for lab {self.lab_name}")
        for cap in scenario.requires:
            if cap not in self.capabilities:
                reasons.append(f"missing capability {cap}")
        target = None
        try:
            target = self.resolve_target(scenario, host)
        except ScenarioRefused as e:
            reasons.extend(r for r in e.reasons if r not in reasons)
        enabled_names = {e.name for e in enabled}
        if target is not None:
            if any(e.name == name and e.target == target for e in enabled):
                reasons.append(f"already enabled on {target}")
        for dep in scenario.depends:
            if target is None or self.host_domains is None:
                if dep not in enabled_names:
                    reasons.append(f"requires scenario {dep}")
                continue
            domain = self.domain_of(target)
            if not any(e.name == dep and self.domain_of(e.target) == domain for e in enabled):
                reasons.append(f"requires scenario {dep} in domain {domain}")
        for entry in enabled:
            other = self.scenarios.get(entry.name)
            if entry.name in scenario.conflicts or (other is not None and name in other.conflicts):
                reasons.append(f"conflicts with {entry.key}")
        if target is not None:
            for entry in enabled:
                other = self.scenarios.get(entry.name)
                if other is None or entry.target != target:
                    continue
                for setting in scenario.touches:
                    if setting in other.touches:
                        reasons.append(f"{entry.key} already changes {setting} on {target}")
        if reasons:
            raise ScenarioRefused(reasons)
        return target

    def available(self, enabled: List[EnabledScenario]) -> List[Tuple[Scenario, List[str]]]:
        result = []
        for scenario in self.scenarios.all():
            try:
                self.check_enable(scenario.name, None, enabled)
                result.append((scenario, []))
            except ScenarioRefused as e:
                # the default target may fail where another candidate host passes (depends per domain)
                if any(self._enable_ok(scenario.name, host, enabled) for host in self._candidates(scenario)):
                    result.append((scenario, []))
                else:
                    result.append((scenario, e.reasons))
        return result

    def _candidates(self, scenario: Scenario) -> List[str]:
        if scenario.target:
            return list((self.capabilities or {}).get(scenario.target) or [])
        return list(self.dcs)

    def _enable_ok(self, name: str, host: str, enabled: List[EnabledScenario]) -> bool:
        try:
            self.check_enable(name, host, enabled)
            return True
        except ScenarioRefused:
            return False

    def install_order(self, names: List[str]) -> List[str]:
        requested = set(names)
        order = []
        done = set()
        visiting = set()

        def visit(name):
            if name in done:
                return
            if name in visiting:
                raise ScenarioRefused([f"dependency cycle at {name}"])
            scenario = self.scenarios.get(name)
            if scenario is None:
                raise ScenarioRefused([f"unknown scenario {name}"])
            visiting.add(name)
            for dep in scenario.depends:
                if dep in requested:
                    visit(dep)
            visiting.discard(name)
            done.add(name)
            order.append(name)

        for name in names:
            visit(name)
        return order

    def dependents(self, name: str, enabled: List[EnabledScenario],
                   target: Optional[str] = None) -> List[EnabledScenario]:
        # with a target, only dependents in the target's domain count
        if target is not None:
            domain = self.domain_of(target)
            enabled = [e for e in enabled if self.domain_of(e.target) == domain]
        result = []
        seen = {name}

        def visit(parent):
            for entry in enabled:
                scenario = self.scenarios.get(entry.name)
                if scenario is None or entry.name in seen or parent not in scenario.depends:
                    continue
                seen.add(entry.name)
                visit(entry.name)
                result.extend(e for e in enabled if e.name == entry.name)

        visit(name)
        return result
