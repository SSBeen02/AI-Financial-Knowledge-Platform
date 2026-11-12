

# 목적: 모든 담당자가 같은 로컬 백엔드 회귀 묶음을 실행한다.
# 제한: 배포 사이트/공유 계정/실제 DB·LLM·Qdrant에 요청하지 않는다.
# 수동 UI 통합시험, 첫 글자 시간, 실제 게임 보상과 사용자 시험의 통과 증거가 아니다.
param([string]$Python = "python")
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$oldPythonPath = $env:PYTHONPATH
$oldTmp = $env:TMP
$oldTemp = $env:TEMP
$testTmp = Join-Path $repo ".test-tmp"
New-Item -ItemType Directory -Path $testTmp -Force | Out-Null
$env:TMP = $testTmp
$env:TEMP = $testTmp

$env:PYTHONPATH = "$repo\.test-deps;$repo\rag\chatbot_module;$repo\quiz-upload;$repo"
$groups = @(
    @{ Name = "Stage 1-5 catalog and RAG learning/quiz contracts"; Dir = "rag\chatbot_module"; Tests = @("tests\test_concepts.py", "tests\test_learning_management_schema.py", "tests\test_quiz_integration.py", "tests\test_messages.py", "tests\test_state.py") },
    @{ Name = "Quiz grading, duplicate submit and Stage 5 fixed bank"; Dir = "quiz-upload"; Tests = @("tests\test_team_quiz_adapter.py") },
    @{ Name = "Integrated auth, pretest, game and learning notes"; Dir = "."; Tests = @("tests\test_stage_catalog_contract.py", "tests\test_server_integration.py", "tests\test_pretest_integration.py", "tests\test_game_plan.py", "tests\test_review_records.py") }
)
try {
    foreach ($group in $groups) {
        Write-Host "Running: $($group.Name)"
        Push-Location (Join-Path $repo $group.Dir)
        try {
            & $Python -m pytest @($group.Tests) -q
            if ($LASTEXITCODE -ne 0) { throw "$($group.Name) failed (exit $LASTEXITCODE)" }
        } finally { Pop-Location }
    }
    Write-Host "PASS: local backend regression. Record commit and output; continue browser integration separately."
} finally {
    $env:PYTHONPATH = $oldPythonPath
    $env:TMP = $oldTmp
    $env:TEMP = $oldTemp
}
