﻿<#
.SYNOPSIS
    註冊或移除 Facebook 監控的 Windows 工作排程器（開機登入自動靜默背景啟動）。

.DESCRIPTION
    此腳本會在 Windows 工作排程器中建立名為 "FacebookMonitor" 的工作：
    - 觸發時機：目前使用者登入 Windows 時
    - 執行程式：專案虛擬環境中的 pythonw.exe（無視窗、零彈窗）
    - 執行參數：-X utf8 main.py run
    - 電池設定：筆記型電腦使用電池時亦持續運行
    - 錯誤重啟：程序意外中斷時自動嘗試重啟

.PARAMETER Install
    註冊並啟動排程工作（預設行為）。

.PARAMETER Uninstall
    停止並移除已註冊的排程工作。

.PARAMETER Status
    查詢目前工作排程器的註冊與運行狀態。
#>

[CmdletBinding(DefaultParameterSetName = 'Install')]
param (
    [Parameter(ParameterSetName = 'Install')]
    [switch]$Install,

    [Parameter(ParameterSetName = 'Uninstall')]
    [switch]$Uninstall,

    [Parameter(ParameterSetName = 'Status')]
    [switch]$Status
)

$ErrorActionPreference = 'Stop'
$TaskName = "FacebookMonitor"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
$mainPy = Join-Path $projectRoot "main.py"

function Check-Environment {
    if (-not (Test-Path -LiteralPath $pythonw)) {
        throw "找不到 pythonw.exe，請先執行 powershell -File scripts/setup-background.ps1 建立虛擬環境。"
    }
    if (-not (Test-Path -LiteralPath $mainPy)) {
        throw "找不到 main.py，請確認腳本位於專案目錄內。"
    }
}

if ($Uninstall) {
    Write-Host "[*] 正在檢查排程工作: $TaskName ..." -ForegroundColor Cyan
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "[*] 停止排程工作..." -ForegroundColor Yellow
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Write-Host "[*] 移除排程工作..." -ForegroundColor Yellow
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "[+] 已成功移除排程工作 $TaskName。" -ForegroundColor Green
    } else {
        Write-Host "[i] 排程工作 $TaskName 不存在，無需移除。" -ForegroundColor Gray
    }
    exit 0
}

if ($Status) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        $info = Get-ScheduledTaskInfo -TaskName $TaskName
        Write-Host "=== Facebook 監控排程工作狀態 ===" -ForegroundColor Cyan
        Write-Host "工作名稱: $($existing.TaskName)"
        Write-Host "目前狀態: $($existing.State)"
        Write-Host "上次執行時間: $($info.LastRunTime)"
        Write-Host "上次執行結果: $($info.LastTaskResult)"
        Write-Host "下次執行時間: $($info.NextRunTime)"
    } else {
        Write-Host "[i] 排程工作 $TaskName 尚未安裝。" -ForegroundColor Yellow
    }
    exit 0
}

# 預設執行 Install
Check-Environment
Write-Host "[*] 正在註冊 Windows 工作排程器: $TaskName ..." -ForegroundColor Cyan

# 移除既有相同名稱工作
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[*] 發現已存在的排程工作，正在更新..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# 定義動作：使用 pythonw.exe 執行 main.py run，工作目錄指向專案根目錄
$action = New-ScheduledTaskAction `
    -Execute $pythonw `
    -Argument "-X utf8 `"$mainPy`" run" `
    -WorkingDirectory $projectRoot

# 定義觸發器：使用者登入時
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# 定義設定：筆電電池執行、失敗自動重試、永不逾時、無視窗
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval ([TimeSpan]::FromMinutes(1))

# 定義主體：目前登入的使用者權限
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

# 註冊工作
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Facebook 背景輕量無彈窗監控程式" | Out-Null

Write-Host "[+] 成功註冊排程工作: $TaskName" -ForegroundColor Green
Write-Host "    - 觸發時機: 登入 Windows 自動背景啟動"
Write-Host "    - 執行模式: pythonw 零終端機、零彈窗靜默運行"
Write-Host "    - 專案目錄: $projectRoot"
Write-Host ""
Write-Host "[*] 正在啟動背景監控程序..." -ForegroundColor Cyan
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 2

$info = Get-ScheduledTask -TaskName $TaskName
Write-Host "[+] 排程工作目前狀態: $($info.State)" -ForegroundColor Green
Write-Host "如需查看運行狀態請執行: .venv\Scripts\python.exe -X utf8 main.py status" -ForegroundColor Gray
Write-Host "如需移除排程請執行: powershell -File scripts/setup-task-scheduler.ps1 -Uninstall" -ForegroundColor Gray
