from goad.extension import Extension
from goad.provider.provider_factory import ProviderFactory
from goad.utils import *
from goad.goadpath import GoadPath
from goad.log import Log
from goad.scenario import Scenarios
from goad.scenario_resolver import ScenarioResolver
import json
from goad.exceptions import *


class Labs:
    def __init__(self, config):
        self.labs = {}
        for lab_name in Utils.list_folders(GoadPath.get_labs_path()):
            if lab_name != 'TEMPLATE':
                try:
                    self.labs[lab_name] = Lab(lab_name, config)
                except ProviderPathNotFound as e:
                    Log.warning(f'lab {lab_name} not loaded provider path not found')

    def get_lab(self, lab_name):
        if lab_name not in self.labs.keys():
            return None
        return self.labs[lab_name]

    def get_labs_list(self):
        return list(self.labs.values())

    def is_exist(self, lab_name):
        return lab_name in self.labs.keys()


class Lab:
    def __init__(self, lab_name, config):
        self.lab_name = lab_name
        self.providers = {}
        self.extensions = {}
        self.capabilities = None
        self.dcs = []
        self.host_domains = {}
        self.root_dc = ''
        self._scenario_resolver = None
        self._load_lab_config(lab_name)
        try:
            self._load_providers(lab_name, config)
        except FileNotFoundError as e:
            raise ProviderPathNotFound(e)
        try:
            self._load_extensions(lab_name)
        except FileNotFoundError as e:
            # no extensions
            pass

    def _load_lab_config(self, lab_name):
        config_file = GoadPath.get_lab_data_path(lab_name) + os.path.sep + 'config.json'
        try:
            with open(config_file, 'r') as config_openfile:
                lab_config = json.load(config_openfile)['lab']
            capabilities = lab_config.get('capabilities')
            hosts = lab_config.get('hosts', {})
            domains = lab_config.get('domains', {})
            dcs = [key for key, host in hosts.items() if host.get('type') == 'dc']
            root_dc = self._find_root_dc(domains)
            host_domains = {key: host.get('domain', '') for key, host in hosts.items()}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return
        self.capabilities = capabilities
        self.dcs = dcs
        self.host_domains = host_domains
        self.root_dc = root_dc

    @staticmethod
    def _find_root_dc(domains):
        def is_child(name):
            return any(name.endswith('.' + other) for other in domains if other != name)

        roots = [name for name in domains if not is_child(name)]
        if not roots:
            return ''

        def children_count(root):
            return sum(1 for name in domains if name.endswith('.' + root))

        # most child domains first, tie: lowest dc key
        best = sorted(roots, key=lambda root: (-children_count(root), domains[root]['dc']))[0]
        return domains[best]['dc']

    def is_base(self):
        return self.capabilities is not None

    def get_scenario_resolver(self):
        if self._scenario_resolver is None:
            scenarios = Scenarios(GoadPath.get_scenarios_path())
            self._scenario_resolver = ScenarioResolver(scenarios, self.lab_name, self.capabilities, self.root_dc, self.dcs,
                                                       self.host_domains)
        return self._scenario_resolver

    def get_scenario(self, name):
        return self.get_scenario_resolver().scenarios.get(name)

    def _load_providers(self, lab_name, config):
        for provider_name in Utils.list_folders(GoadPath.get_lab_providers_path(lab_name)):
            provider = ProviderFactory.get_provider(provider_name, lab_name, config)
            if provider is not None:
                self.providers[provider_name] = provider

    def _load_extensions(self, lab_name):
        for extension_name in Utils.list_folders(GoadPath.get_extensions_path()):
            extension = Extension(extension_name)
            if extension.is_available(lab_name):
                self.extensions[extension_name] = extension

    def get_provider(self, provider_name):
        if provider_name not in self.providers.keys():
            return None
        return self.providers[provider_name]

    def get_first_provider_name(self):
        return next(iter(self.providers))

    def get_extension(self, extension_name):
        if extension_name in self.extensions.keys():
            return self.extensions[extension_name]
        else:
            return None

    def get_list_extensions_name(self):
        return list(self.extensions.keys())

    def show_extensions(self):
        for extension_name in self.extensions.keys():
            self.extensions[extension_name].show()
