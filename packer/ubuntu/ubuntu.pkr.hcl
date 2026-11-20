locals {
  user = "goad"
  sudo = "echo '${var.password}' | sudo -S -E bash '{{ .Path }}'"
}

source "vmware-iso" "ubuntu" {
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

  # autoinstall reads user-data/meta-data from a disc labelled cidata
  cd_label = "cidata"
  cd_content = {
    "meta-data" = ""
    "user-data" = templatefile("${path.root}/http/user-data.pkrtpl.yml", {
      user          = local.user
      password_hash = bcrypt(var.password)
    })
  }

  boot_wait = "5s"
  boot_command = [
    "c<wait2s>",
    "linux /casper/vmlinuz --- autoinstall<enter><wait2s>",
    "initrd /casper/initrd<enter><wait2s>",
    "boot<enter>"
  ]

  communicator = "ssh"
  ssh_username = local.user
  ssh_password = var.password
  ssh_timeout  = "1h"

  shutdown_command = "echo '${var.password}' | sudo -S shutdown -P now"
}

build {
  sources = ["source.vmware-iso.ubuntu"]

  dynamic "provisioner" {
    labels   = ["file"]
    for_each = var.ca_dir == "" ? [] : [1]
    content {
      source      = "${var.ca_dir}/"
      destination = "/tmp/goad-ca"
    }
  }

  provisioner "shell" {
    execute_command  = local.sudo
    environment_vars = ["GOAD_CA_EXPECTED=${var.ca_dir == "" ? "0" : "1"}"]
    scripts = [
      "${path.root}/scripts/base.sh",
      "${path.root}/scripts/import-ca.sh",
      "${path.root}/scripts/cloud-init-reset.sh",
    ]
  }
}
