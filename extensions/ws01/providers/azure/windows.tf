"ws01" = {
  name               = "ws01"
  publisher          = "MicrosoftWindowsDesktop"
  offer              = "office-365"
  windows_sku        = "win10-22h2-avd-m365"
  windows_version    = "latest"
  private_ip_address = "{{ip_range}}.31"
  password           = "Aa1234567890!"
  size               = "Standard_B2s"
}