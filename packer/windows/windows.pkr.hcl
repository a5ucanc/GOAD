locals {
  setup_user = "goad-setup"
}

source "vmware-iso" "windows" {
  vm_name          = var.vm_name
  output_directory = var.output_directory
  iso_url          = var.iso_url
  iso_checksum     = var.iso_checksum

  guest_os_type        = var.guest_os_type
  version              = 21
  firmware             = "efi"
  cpus                 = var.cpus
  memory               = var.memory
  disk_size            = var.disk_size
  disk_adapter_type    = "nvme"
  disk_type_id         = 0
  cdrom_adapter_type   = "sata"
  network              = "nat"
  network_adapter_type = "e1000e"
  headless             = true
  vmx_data = {
    "tools.syncTime" = "TRUE"
  }

  tools_mode        = "attach"
  tools_source_path = var.tools_iso

  # Windows Setup reads autounattend.xml from the root of any attached disc
  cd_label = "goad"
  cd_content = {
    "autounattend.xml" = templatefile("${path.root}/answer/autounattend.pkrtpl.xml", {
      password   = var.password
      image_name = var.image_name
      setup_user = local.setup_user
      is_win11   = var.is_win11
    })
    "bootstrap.ps1" = file("${path.root}/scripts/bootstrap.ps1")
  }
  cd_files = compact([var.ca_dir])

  # EFI shows "Press any key to boot from CD" for a few seconds
  boot_wait    = "2s"
  boot_command = ["<spacebar><wait1s><spacebar><wait1s><spacebar><wait1s><spacebar>"]

  communicator   = "winrm"
  winrm_username = local.setup_user
  winrm_password = var.password
  winrm_timeout  = "2h"

  shutdown_command = "C:\\Windows\\System32\\Sysprep\\sysprep.exe /generalize /oobe /shutdown /quiet /unattend:C:\\goad\\unattend.xml"
  shutdown_timeout = "1h"
}

build {
  sources = ["source.vmware-iso.windows"]

  provisioner "powershell" {
    scripts = ["${path.root}/scripts/install-vmware-tools.ps1"]
  }
  provisioner "windows-restart" {
    restart_timeout = "20m"
  }
  provisioner "powershell" {
    scripts = ["${path.root}/scripts/import-ca.ps1", "${path.root}/scripts/base-settings.ps1"]
  }

  dynamic "provisioner" {
    labels   = ["windows-update"]
    for_each = var.windows_updates ? [1] : []
    content {
      search_criteria = "IsInstalled=0"
      filters         = ["exclude:$_.Title -like '*Preview*'", "include:$true"]
      update_limit    = 50
    }
  }

  provisioner "powershell" {
    environment_vars = ["GOAD_IS_SERVER=${var.is_server}"]
    scripts          = ["${path.root}/scripts/install-features.ps1"]
  }
  provisioner "windows-restart" {
    restart_timeout = "20m"
  }

  provisioner "file" {
    content     = templatefile("${path.root}/sysprep/unattend.pkrtpl.xml", { password = var.password })
    destination = "C:/goad/unattend.xml"
  }
  provisioner "file" {
    source      = "${path.root}/scripts/firstboot.ps1"
    destination = "C:/goad/firstboot.ps1"
  }
  provisioner "file" {
    source      = "${path.root}/sysprep/SetupComplete.cmd"
    destination = "C:/Windows/Setup/Scripts/SetupComplete.cmd"
  }
  provisioner "powershell" {
    environment_vars = ["GOAD_IS_WIN11=${var.is_win11}"]
    scripts          = ["${path.root}/scripts/cleanup.ps1"]
  }
}
