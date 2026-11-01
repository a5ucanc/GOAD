# vmware bug to set the ip
# see : https://github.com/hashicorp/vagrant/issues/5000#issuecomment-258209286

param ([String] $ip)

# Re-applying the address resets the adapter : when vagrant already talks WinRM over this ip (vagrant up retry
# / --provision) the session drops and vagrant hangs forever, so only set it when it is not there yet.
$current = Get-NetIPAddress -InterfaceAlias Ethernet1 -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -eq $ip -and $_.PrefixOrigin -eq 'Manual' }
if ($current) {
  Write-Output "Ethernet1 already set to $ip"
  exit 0
}

netsh.exe int ip set address Ethernet1 static $ip 255.255.255.0
