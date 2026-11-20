$ErrorActionPreference = 'Continue'
# Drop superseded components left by Windows Update. A restart must follow before sysprep:
# WinRM can stop answering after this runs.
Dism.exe /Online /Cleanup-Image /StartComponentCleanup /ResetBase /Quiet
exit 0
