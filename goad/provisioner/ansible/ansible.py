import os.path
import yaml
from goad.utils import *
from goad.log import Log
from goad.provisioner.provisioner import Provisioner
from goad.goadpath import GoadPath


class Ansible(Provisioner):

    def _get_lab_inventory(self, lab_name, provider_name):
        inventory = []
        # Lab inventory
        lab_inventory = GoadPath.get_lab_inventory_file(lab_name)
        if os.path.isfile(lab_inventory):
            inventory.append(lab_inventory)
            Log.success(f'Lab inventory : {lab_inventory} file found')
        # lab instance inventory
        instance_inventory = self.instance_path + os.path.sep + 'inventory'
        if os.path.isfile(instance_inventory):
            inventory.append(instance_inventory)
            Log.success(f'Provider inventory : {instance_inventory} file found')
        return inventory

    def _get_global_inventory(self):
        # Global inventory
        global_inventory = GoadPath.get_global_inventory_path()
        if os.path.isfile(global_inventory):
            Log.success(f'Global inventory : {global_inventory} file found')
            return global_inventory
        return None

    def get_inventory(self, lab_name, provider_name):
        Log.info('Loading inventory')
        inventory = self._get_lab_inventory(lab_name, provider_name)
        global_inventory = self._get_global_inventory()
        if global_inventory is not None:
            inventory.append(global_inventory)
        return inventory

    def get_playbook_list(self, lab_name):
        Log.info('Loading playbook list')
        playbook_organisation_file = GoadPath.get_playbooks_lab_config()
        playbook_list = []
        with open(playbook_organisation_file, 'r') as playbooks:
            data_loaded = yaml.safe_load(playbooks)
        if lab_name in data_loaded:
            playbook_datas = data_loaded[lab_name]
        else:
            playbook_datas = data_loaded['default']

        # validate playbooks
        for playbook in playbook_datas:
            playbook_path = GoadPath.get_provisioner_path() + playbook
            if not os.path.isfile(playbook_path):
                Log.error(f'{playbook} not valid, file {playbook_path} not found')
            else:
                playbook_list.append(playbook)
                Log.success(f'{playbook} file found')
        return playbook_list

    def run(self, playbook=None):
        inventory = self.get_inventory(self.lab_name, self.provider_name)
        provision_result = False
        if playbook is None:
            playbooks = self.get_playbook_list(self.lab_name)
            for playbook in playbooks:
                provision_result = self.run_playbook(playbook, inventory)
                if not provision_result:
                    Log.error(f'Something wrong during the provisioning task : {playbook}')
                    return False
        else:
            provision_result = self.run_playbook(playbook, inventory)
        return provision_result

    def run_extension(self, extension, current_instance_extensions_name, install=True, use_disable_vagrant_inventory=False):
        inventory = []
        if use_disable_vagrant_inventory:
            inventory += self._get_disable_vagrant_lab_inventory()
        inventory += self._get_lab_inventory(self.lab_name, self.provider_name)

        # add the inventory of other enabled extensions
        for instances_extension_name in current_instance_extensions_name:
            if instances_extension_name != extension.name:
                other_extension_inventory = self.instance_path + os.path.sep + instances_extension_name + '_inventory'
                if other_extension_inventory is not None:
                    inventory.append(other_extension_inventory)

        # add the current extension inventory at the end
        extension_inventory = self.instance_path + os.path.sep + extension.name + '_inventory'
        if extension_inventory is not None:
            inventory.append(extension_inventory)

        global_inventory = self._get_global_inventory()
        if global_inventory is not None:
            inventory.append(global_inventory)

        playbook = extension.get_playbook(install)
        extension_ansible_path = extension.get_ansible_path()

        provision_result = self.run_playbook(playbook, inventory, playbook_path=extension_ansible_path)
        if not provision_result:
            Log.error(f'Something wrong during the provisioning task : {playbook}')
            return False
        return provision_result

    def _get_disable_vagrant_lab_inventory(self):
        # inventory_disable_vagrant must come FIRST, before the normal lab inventories:
        # - its Windows hosts carry host-level administrator credentials, which beat the
        #   [all:vars] ansible_user/ansible_password of the inventories loaded after it;
        # - its own [all:vars] (ansible_user=notused) is overridden by the lab inventory, so
        #   linux hosts (extensions) keep the lab credentials and all the lab vars and groups.
        inventory = []
        lab_inventory = self.instance_path + os.path.sep + 'inventory_disable_vagrant'
        if os.path.isfile(lab_inventory):
            inventory.append(lab_inventory)
            Log.success(f'Lab inventory disable_vagrant : {lab_inventory} file found')
        return inventory

    def run_scenario(self, scenario, target, current_instance_extensions_name, install=True):
        inventory = self._get_disable_vagrant_lab_inventory()
        inventory += self._get_lab_inventory(self.lab_name, self.provider_name)

        # add the inventory of enabled extensions (only if the file exists)
        for extension_name in current_instance_extensions_name:
            extension_inventory = self.instance_path + os.path.sep + extension_name + '_inventory'
            if os.path.isfile(extension_inventory):
                inventory.append(extension_inventory)

        # add the scenario run inventory after the lab and extension inventories
        scenario_inventory = self.instance_path + os.path.sep + 'scenario_run_inventory'
        with open(scenario_inventory, 'w') as f:
            f.write(f'[scenario_target]\n{target}\n\n[all:vars]\nscenario_name={scenario.name}\nscenario_target={target}\n')
        inventory.append(scenario_inventory)

        global_inventory = self._get_global_inventory()
        if global_inventory is not None:
            inventory.append(global_inventory)

        if self.use_jumpbox:
            # the playbook runs on the jumpbox: push the scenario files and the run inventory written above
            self.sync_source_jumpbox()

        playbook = scenario.get_playbook(install)
        scenario_ansible_path = scenario.get_ansible_path() + os.path.sep

        provision_result = self.run_playbook(playbook, inventory, playbook_path=scenario_ansible_path)
        if not provision_result:
            Log.error(f'Something wrong during the provisioning task : {playbook}')
            return False
        return provision_result

    def run_shutdown(self, hosts, current_instance_extensions_name):
        """Shut the hosts down from inside (administrator inventory first, as for scenarios)."""
        inventory = self._get_disable_vagrant_lab_inventory()
        inventory += self._get_lab_inventory(self.lab_name, self.provider_name)
        for extension_name in current_instance_extensions_name:
            extension_inventory = self.instance_path + os.path.sep + extension_name + '_inventory'
            if os.path.isfile(extension_inventory):
                inventory.append(extension_inventory)
        shutdown_inventory = self.instance_path + os.path.sep + 'shutdown_inventory'
        with open(shutdown_inventory, 'w') as f:
            f.write('[shutdown_target]\n' + '\n'.join(hosts) + '\n')
        inventory.append(shutdown_inventory)
        global_inventory = self._get_global_inventory()
        if global_inventory is not None:
            inventory.append(global_inventory)
        if self.use_jumpbox:
            self.sync_source_jumpbox()
        # one try: a second run would find hosts already going down
        return self.run_playbook('shutdown.yml', inventory, tries=0)

    def run_from(self, task):
        inventory = self.get_inventory(self.lab_name, self.provider_name)
        playbooks = self.get_playbook_list(self.lab_name)

        if task == '' or task is None:
            Log.error('Missing playbook to start from')
            Log.info('Playbook list :')
            for playbook in playbooks:
                Log.info(f' - {playbook}')
            return False

        skip = True
        for playbook in playbooks:
            if playbook == task:
                skip = False
            if skip:
                Log.info(f'skip {playbook}')
            else:
                provision_result = self.run_playbook(playbook, inventory)
                if not provision_result:
                    Log.error(f'Something wrong during the provisioning task : {playbook}')
                    return False
        return True

    def run_playbook(self, playbook, inventories, tries=3, timeout=30, playbook_path=None):
        # abstract
        pass

    def run_sync_time(self):
        inventory = self._get_disable_vagrant_lab_inventory()
        inventory += self._get_lab_inventory(self.lab_name, self.provider_name)
        global_inventory = self._get_global_inventory()
        if global_inventory is not None:
            inventory.append(global_inventory)
        return self.run_playbook('sync_time.yml', inventory)

    def get_disable_vagrant_inventory(self):
        Log.info('Loading inventory')
        inventory = self._get_disable_vagrant_lab_inventory()
        global_inventory = self._get_global_inventory()
        if global_inventory is not None:
            inventory.append(global_inventory)
        return inventory

    def run_disable_vagrant(self, disable_vagrant=True):
        inventory = self.get_disable_vagrant_inventory()
        if disable_vagrant:
            playbook = 'disable_vagrant.yml'
        else:
            playbook = 'enable_vagrant.yml'
        provision_result = self.run_playbook(playbook, inventory)
        if not provision_result:
            Log.error(f'Something wrong during the provisioning task : {playbook}')
            return False
        return provision_result
