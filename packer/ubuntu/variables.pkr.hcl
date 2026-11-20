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

# From ubuntu2404.pkrvars.hcl
variable "guest_os_type" { type = string }

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
  default = 40960
}
