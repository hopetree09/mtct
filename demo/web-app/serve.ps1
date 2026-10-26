# 启动演示站（默认 8765 端口）
param([int]$Port = 8765)
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "DemoX demo site: http://127.0.0.1:$Port/" -ForegroundColor Cyan
python -m http.server $Port --bind 127.0.0.1 --directory $root
