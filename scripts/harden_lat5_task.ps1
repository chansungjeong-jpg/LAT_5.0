# LAT5 daily pipeline task hardening (run ONCE, as Administrator).
#
# Why: on 2026-09-29..10-03 the 16:00 run failed or stalled because the PC was off/asleep
#   - 09-29 PC off at 16:00, task fired at 20:35 right after boot -> 0x80070520 (no logon session yet)
#   - 10-01 PC asleep at 16:00, fired 18:36 right after wake      -> 0x80070520
#   - 10-03 PC went to sleep 16:27 mid-collect, woke next day     -> "database is locked"
# The task ran with StartWhenAvailable=False, WakeToRun=False, RestartCount=0.
#
# Changes ONLY the task LAT5_Monthly10_Weekly5_Recovery. Does not touch the action, trigger,
# principal, other tasks, flag files or power settings. Previous values are printed and saved.
#
# Usage (elevated PowerShell):  powershell -ExecutionPolicy Bypass -File scripts\harden_lat5_task.ps1
# Revert: set StartWhenAvailable/WakeToRun to False and RestartCount to 0 (values below).

$ErrorActionPreference = 'Stop'
$name = 'LAT5_Monthly10_Weekly5_Recovery'

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error 'Administrator rights are required (the task runs as SYSTEM). Re-run from an elevated PowerShell.'
    exit 1
}

$task = Get-ScheduledTask -TaskName $name
$fields = 'StartWhenAvailable', 'WakeToRun', 'RestartCount', 'RestartInterval', 'DisallowStartIfOnBatteries'
$before = $task.Settings | Select-Object $fields
Write-Host 'BEFORE:'; $before | Format-List | Out-String | Write-Host

$logDir = Join-Path (Split-Path $PSScriptRoot -Parent) 'reports\ops'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$before | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $logDir "task_settings_before_$stamp.json")

$settings = $task.Settings
$settings.StartWhenAvailable = $true      # run a missed 16:00 as soon as the PC is available again
$settings.WakeToRun          = $true      # wake the PC for the scheduled run
$settings.RestartCount       = 3          # retry (covers "no logon session yet" right after boot/wake)
$settings.RestartInterval    = 'PT10M'    # 10 minutes apart
Set-ScheduledTask -TaskName $name -Settings $settings | Out-Null

Write-Host 'AFTER:'
(Get-ScheduledTask -TaskName $name).Settings | Select-Object $fields | Format-List | Out-String | Write-Host
Write-Host 'NOTE: DisallowStartIfOnBatteries is unchanged. If this PC is a laptop that runs on battery at 16:00, the task will not start; keep it plugged in or change that setting deliberately.'
