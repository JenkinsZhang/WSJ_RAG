<#
.SYNOPSIS
    WSJ RAG Pipeline 定时任务设置脚本

.DESCRIPTION
    使用 Windows 任务计划程序设置定时运行 pipeline

.EXAMPLE
    # 以管理员身份运行 PowerShell，然后执行：
    .\scripts\schedule_pipeline.ps1

    # 或者指定参数：
    .\scripts\schedule_pipeline.ps1 -Hour 8 -Minute 0 -Categories "tech,finance"
#>

param(
    [int]$Hour = 8,           # 默认早上8点
    [int]$Minute = 0,         # 默认整点
    [string]$Categories = "", # 空=所有分类
    [int]$MaxArticles = 20,   # 每分类最大文章数
    [switch]$Remove,          # 删除已有任务
    [switch]$Status           # 查看任务状态
)

$TaskName = "WSJ-RAG-Pipeline"

# 获取项目根目录 (更可靠的方式)
if ($PSScriptRoot) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
} else {
    # 如果 $PSScriptRoot 为空，使用硬编码路径
    $ProjectRoot = "E:\Programming\Pycharm\WSJRAG"
}

# 验证项目目录
if (-not (Test-Path (Join-Path $ProjectRoot "run_pipeline.py"))) {
    Write-Host "错误: 无法找到项目目录，请在项目根目录运行此脚本" -ForegroundColor Red
    Write-Host "当前检测路径: $ProjectRoot"
    exit 1
}

# 查看状态
if ($Status) {
    Write-Host "`n=== WSJ RAG Pipeline 任务状态 ===" -ForegroundColor Cyan
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        Write-Host "任务名称: $TaskName" -ForegroundColor Green
        Write-Host "状态: $($task.State)"

        $info = Get-ScheduledTaskInfo -TaskName $TaskName
        Write-Host "上次运行: $($info.LastRunTime)"
        Write-Host "下次运行: $($info.NextRunTime)"
        Write-Host "上次结果: $($info.LastTaskResult)"

        # 显示触发器
        $triggers = $task.Triggers
        foreach ($trigger in $triggers) {
            Write-Host "触发时间: $($trigger.StartBoundary)"
        }
    } else {
        Write-Host "任务不存在" -ForegroundColor Yellow
    }
    exit
}

# 删除任务
if ($Remove) {
    Write-Host "`n删除任务: $TaskName" -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "已删除" -ForegroundColor Green
    exit
}

Write-Host "`n=== WSJ RAG Pipeline 定时任务设置 ===" -ForegroundColor Cyan
Write-Host "项目目录: $ProjectRoot"
Write-Host "计划时间: 每天 ${Hour}:$($Minute.ToString('00'))"

# 检查 Python
$PythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $PythonPath) {
    Write-Host "错误: 未找到 Python" -ForegroundColor Red
    exit 1
}
Write-Host "Python: $PythonPath"

# 构建命令参数
$Arguments = "run_pipeline.py"
if ($Categories) {
    $Arguments += " --category $($Categories -replace ',', ' ')"
}
$Arguments += " --max-articles $MaxArticles"

Write-Host "命令: python $Arguments"

# 确保 scripts 目录存在
$ScriptsDir = Join-Path $ProjectRoot "scripts"
if (-not (Test-Path $ScriptsDir)) {
    New-Item -ItemType Directory -Path $ScriptsDir | Out-Null
}

# 创建批处理文件 (更可靠)
$BatchFile = Join-Path $ScriptsDir "run_pipeline.bat"
$BatchContent = @"
@echo off
cd /d "$ProjectRoot"
echo [%date% %time%] Starting WSJ RAG Pipeline...
python $Arguments
echo [%date% %time%] Pipeline finished with exit code %ERRORLEVEL%
"@

Set-Content -Path $BatchFile -Value $BatchContent -Encoding ASCII
Write-Host "创建批处理: $BatchFile" -ForegroundColor Green

# 创建计划任务
Write-Host "`n创建 Windows 计划任务..." -ForegroundColor Cyan

# 删除已有任务
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

# 创建触发器 (每天指定时间)
$Trigger = New-ScheduledTaskTrigger -Daily -At "${Hour}:$($Minute.ToString('00'))"

# 创建动作
$Action = New-ScheduledTaskAction -Execute $BatchFile -WorkingDirectory $ProjectRoot

# 创建设置
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

# 注册任务 (以当前用户身份运行)
try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Trigger $Trigger `
        -Action $Action `
        -Settings $Settings `
        -Description "WSJ RAG 自动爬取和索引" `
        -RunLevel Limited | Out-Null

    Write-Host "`n任务创建成功!" -ForegroundColor Green
    Write-Host "任务名称: $TaskName"
    Write-Host "运行时间: 每天 ${Hour}:$($Minute.ToString('00'))"

    # 显示管理命令
    Write-Host "`n管理命令:" -ForegroundColor Yellow
    Write-Host "  查看状态:  .\scripts\schedule_pipeline.ps1 -Status"
    Write-Host "  删除任务:  .\scripts\schedule_pipeline.ps1 -Remove"
    Write-Host "  手动运行:  schtasks /run /tn $TaskName"
    Write-Host "  打开GUI:   taskschd.msc"

} catch {
    Write-Host "创建失败: $_" -ForegroundColor Red
    Write-Host "`n可能需要管理员权限，请右键以管理员身份运行 PowerShell" -ForegroundColor Yellow
    exit 1
}
