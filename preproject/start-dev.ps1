# FinEdu 개발 서버 실행 스크립트
# 사용법: PowerShell에서 .\start-dev.ps1

$nodePath = "$PSScriptRoot\.tools\node"
$env:Path = "$nodePath;" + $env:Path

# 기존 서버 종료 (3000~3002 포트)
3000..3002 | ForEach-Object {
    Get-NetTCPConnection -LocalPort $_ -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}

Set-Location $PSScriptRoot
Write-Host ""
Write-Host "  FinEdu 개발 서버 시작 중..." -ForegroundColor Cyan
Write-Host "  브라우저에서 http://localhost:3000 접속하세요" -ForegroundColor Yellow
Write-Host ""

npm run dev
