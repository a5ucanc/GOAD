"""goad-v2: one VMware Workstation Active Directory lab, built with Packer and Ansible."""

__version__ = '2.0.0'


class GoadError(Exception):
    """An expected failure with a message for the user; the CLI prints it and exits 1."""
