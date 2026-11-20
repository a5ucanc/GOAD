packer {
  required_version = ">= 1.11.0"
  required_plugins {
    vmware = {
      # 2.x requires Workstation 17.6+
      version = ">= 2.1.0"
      source  = "github.com/hashicorp/vmware"
    }
  }
}
