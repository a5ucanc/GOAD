from goad.utils import *
from goad.goadpath import GoadPath
from goad.log import Log
import json

SCENARIO_TYPES = ('object', 'setting')


class InvalidScenario(Exception):
    pass


class Scenario:

    def __init__(self, name, data):
        self.name = name
        if not isinstance(data, dict):
            raise InvalidScenario('scenario data must be an object')
        if not data.get('description'):
            raise InvalidScenario('description is required')
        if data.get('type') not in SCENARIO_TYPES:
            raise InvalidScenario(f"type must be one of {', '.join(SCENARIO_TYPES)}")
        self.description = data['description']
        self.type = data['type']
        self.requires = list(data.get('requires', []))
        self.target = data.get('target', '')
        self.depends = list(data.get('depends', []))
        self.conflicts = list(data.get('conflicts', []))
        self.touches = list(data.get('touches', []))
        self.labs = list(data.get('labs', ['*']))

    @classmethod
    def from_file(cls, name, path):
        with open(path, 'r') as scenario_file:
            return cls(name, json.load(scenario_file))

    def allowed_on_lab(self, lab_name):
        return '*' in self.labs or lab_name in self.labs

    def get_playbook(self, install=True):
        if install:
            return 'install.yml'
        else:
            return 'uninstall.yml'

    def get_ansible_path(self):
        return GoadPath.get_scenario_ansible_path(self.name)


class Scenarios:

    def __init__(self, scenarios_path):
        self.scenarios = {}
        for name in sorted(Utils.list_folders(scenarios_path)):
            config_file = os.path.join(scenarios_path, name, 'scenario.json')
            try:
                self.scenarios[name] = Scenario.from_file(name, config_file)
            except (InvalidScenario, json.JSONDecodeError, FileNotFoundError) as e:
                Log.warning(f'scenario {name} skipped: {e}')

    def get(self, name):
        return self.scenarios.get(name)

    def all(self):
        return [self.scenarios[n] for n in sorted(self.scenarios)]
