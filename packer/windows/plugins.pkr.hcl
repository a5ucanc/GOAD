packer {
  required_version = ">= 1.11.0"
  required_plugins {
    vmware = {
      version = ">= 1.1.0"
      source  = "github.com/hashicorp/vmware"
    }
    windows-update = {
      version = ">= 0.16.8"
      source  = "github.com/rgl/windows-update"
    }
  }
}
