import subprocess
import time
from goad.command.cmd_factory import CommandFactory
from goad.log import Log
from goad.utils import *
from goad.goadpath import GoadPath


class JumpBox:

    def __init__(self, instance, creation=False):
        self.lab_name = instance.lab_name
        self.instance_id = instance.instance_id
        self.instance_path = instance.instance_path
        self.provider = instance.provider
        self.ssh_key = self.get_jumpbox_key(creation)
        self.username = 'goad'
        self.command = CommandFactory.get_command()

        if not creation:
            self.ip = self.provider.get_jumpbox_ip(instance.ip_range)
            if self.ssh_key is None:
                Log.error('Missing ssh file JumpBox remote connection')
            elif os.path.isfile(self.ssh_key) is None:
                Log.error('Missing ssh file JumpBox remote connection')
            if self.ip is None:
                Log.error('Missing ip for JumpBox remote connection')
        else:
            self.ip = None

    def provision(self):
        script_name = self.provider.jumpbox_setup_script
        script_file = GoadPath.get_script_file(script_name)
        if not os.path.isfile(script_file):
            Log.error(f'script file: {script_file} not found !')
            return None
        self.run_script(script_file)

    def get_jumpbox_key(self, creation=False):
        return self.instance_path + os.path.sep + 'ssh_keys' + os.path.sep + 'ubuntu-jumpbox.pem'

    def ssh(self):
        ssh_cmd = f"ssh -o StrictHostKeyChecking=no -i {self.ssh_key} {self.username}@{self.ip}"
        self.command.run_shell(ssh_cmd, project_path)

    def ssh_proxy(self, port):
        ssh_cmd = f"ssh -o StrictHostKeyChecking=no -D {port} -i {self.ssh_key} {self.username}@{self.ip}"
        self.command.run_shell(ssh_cmd, project_path)

    def run_script(self, script):
        ssh_cmd = f'ssh -o StrictHostKeyChecking=no -i {self.ssh_key} {self.username}@{self.ip} "bash -s" < {script}'
        self.command.run_shell(ssh_cmd, project_path)

    def sync_sources(self):
        """
        rsync ansible folder to the jumpbox ip
        :return:
        """
        # # rsync -a --exclude-from='.gitignore' -e "ssh -o 'StrictHostKeyChecking no' -i $CURRENT_DIR/ad/$lab/providers/$provider/ssh_keys/ubuntu-jumpbox.pem" "$CURRENT_DIR/" goad@$public_ip:~/GOAD/
        source = GoadPath.get_project_path()
        if Utils.is_valid_ipv4(self.ip):
            destination = f'{self.username}@{self.ip}:~/GOAD/'
            self.command.rsync(source, destination, self.ssh_key)

            # workspace
            source = self.instance_path
            destination = f'{self.username}@{self.ip}:~/GOAD/workspace/'
            self.command.rsync(source, destination, self.ssh_key, False)
        else:
            Log.error('Can not sync source jumpbox ip is invalid')

    def is_reachable(self):
        ssh_cmd = f'ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 -o BatchMode=yes -i {self.ssh_key} {self.username}@{self.ip} true'
        try:
            result = subprocess.run(ssh_cmd, cwd=project_path, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return result.returncode == 0
        except Exception:
            return False

    def is_playbook_running(self, playbook, wait=300):
        """
        check if a playbook started by scripts/run_playbook_detached.sh is still running on the jumpbox
        (wait up to `wait` seconds for the jumpbox to be reachable again)
        """
        pid_file = '/tmp/goad_' + playbook.replace('/', '_').replace('.', '_') + '.pid'
        ssh_cmd = f'ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 -o BatchMode=yes -i {self.ssh_key} {self.username}@{self.ip} "test -f {pid_file} && kill -0 $(cat {pid_file})"'
        waited = 0
        while waited <= wait:
            if not self.is_reachable():
                time.sleep(15)
                waited += 15
                continue
            try:
                result = subprocess.run(ssh_cmd, cwd=project_path, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return result.returncode == 0
            except Exception:
                return False
        return False

    def run_command(self, command, path):
        # keepalives : the ansible playbooks can run for hours with no output (ex: MECM setup), without them the
        # ssh session can be reset ("client_loop: send disconnect: Connection reset") and the provisioning aborted
        ssh_cmd = f'ssh -t -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -o ServerAliveCountMax=20 -i {self.ssh_key} {self.username}@{self.ip} "cd {path} && {command}"'
        result = self.command.run_command(ssh_cmd, project_path)
        return result
