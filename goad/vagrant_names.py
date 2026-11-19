import re

_NAME = re.compile(r':name\s*=>\s*"([^"]+)"')


def vm_names_in(vagrantfile_text):
    """VM names declared in a GOAD Vagrantfile (`:name => "<lab>-<HOST>"` entries)."""
    return _NAME.findall(vagrantfile_text)
