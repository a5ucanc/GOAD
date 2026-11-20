# Passed by goad on every build
variable "iso_url" { type = string }
variable "iso_checksum" { type = string }
variable "output_directory" { type = string }
variable "vm_name" { type = string }
variable "password" {
  type      = string
  sensitive = true
}
variable "ca_dir" {
  type    = string
  default = ""
}

# Per OS, from <os>.pkrvars.hcl
variable "guest_os_type" { type = string }
variable "image_name" { type = string }
variable "is_server" { type = bool }
variable "is_win11" {
  type    = bool
  default = false
}

variable "cpus" {
  type    = number
  default = 2
}
variable "memory" {
  type    = number
  default = 4096
}
variable "disk_size" {
  type    = number
  default = 61440
}
variable "windows_updates" {
  type    = bool
  default = true
}

# VMware Tools for Windows, shipped with Workstation
variable "tools_iso" {
  type    = string
  default = "C:\\Program Files (x86)\\VMware\\VMware Workstation\\windows.iso"
}
