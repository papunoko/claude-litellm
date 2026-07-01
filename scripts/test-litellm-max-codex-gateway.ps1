# Run behavior tests for the Claude Max + ChatGPT/Codex LiteLLM gateway.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$UvToolPython = Join-Path $env:APPDATA "uv\tools\litellm\Scripts\python.exe"
if (Test-Path -LiteralPath $UvToolPython) {
    & $UvToolPython -m unittest discover -s tests -p "test_*.py"
    $TestExitCode = $LASTEXITCODE
} else {
    python -m unittest discover -s tests -p "test_*.py"
    $TestExitCode = $LASTEXITCODE
}

if ($null -eq $TestExitCode) {
    $TestExitCode = 0
}

exit $TestExitCode
