from goad.utils import *
from goad.goadpath import GoadPath
from goad.log import Log
import json


class Extension:

    def __init__(self, extension_name):
        self.name = extension_name
        self.providers_name_list = self.load_extension_providers(extension_name)
        self.compatibility = []
        self.description = ''
        self.capabilities = {}
        self.load_extension_config_file(extension_name)

    def load_extension_providers(self, extension_name):
        providers_name_list = []
        for provider_name in Utils.list_folders(GoadPath.get_extension_providers_path(extension_name)):
            if provider_name in ALLOWED_PROVIDERS:
                providers_name_list.append(provider_name)
        return providers_name_list

    def load_extension_config_file(self, extension_name):
        extension_json_file = GoadPath.get_extension_config_file(extension_name)
        if os.path.isfile(extension_json_file):
            with open(extension_json_file, 'r') as extension_json_openfile:
                # Reading from json file
                extension_info = json.load(extension_json_openfile)
                self.compatibility = extension_info['compatibility']
                self.description = extension_info['description']
                capabilities = extension_info.get('capabilities')
                self.capabilities = capabilities if isinstance(capabilities, dict) else {}

    def is_available(self, lab_name):
        return '*' in self.compatibility or lab_name in self.compatibility

    def capabilities_for(self, lab_name):
        """Capabilities this extension grants on lab_name, as {capability: [host, ...]}."""
        lab_capabilities = self.capabilities.get(lab_name)
        if not isinstance(lab_capabilities, dict):
            return {}
        return {key: list(hosts) for key, hosts in lab_capabilities.items()
                if isinstance(hosts, list) and all(isinstance(h, str) for h in hosts)}

    def list_providers_name(self):
        return self.providers_name_list

    def get_playbook(self, install=True):
        if install:
            return 'install.yml'
        else:
            return 'uninstall.yml'

    def has_uninstall(self):
        return os.path.isfile(os.path.join(self.get_ansible_path(), self.get_playbook(install=False)))

    def get_ansible_path(self):
        return GoadPath.get_extension_ansible_path(self.name)

    def show(self):
        name = f'{self.name}'.ljust(30, '.')
        Log.info(f'{name} {self.description}')
