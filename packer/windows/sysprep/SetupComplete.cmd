@echo off
if not exist C:\goad mkdir C:\goad
powershell -NoProfile -ExecutionPolicy Bypass -File C:\goad\firstboot.ps1 >> C:\goad\firstboot.log 2>&1
