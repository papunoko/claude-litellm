# Start LiteLLM gateway with both Claude Max OAuth and ChatGPT/Codex
# subscription models exposed to Claude Code.
param(
    [int]$Port = 4000,
    [string]$BindHost = "127.0.0.1",
    [string]$MasterKey = "",
    [string]$Config = "litellm_config.max-codex-subscriptions.yaml",
    [string]$ChatGptTokenDir = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$ConfigPath = (Resolve-Path $Config).Path

Get-Command litellm -ErrorAction Stop | Out-Null

if (-not $MasterKey) {
    $MasterKey = $env:LITELLM_MASTER_KEY
}

if (-not $MasterKey) {
    throw "Set -MasterKey or LITELLM_MASTER_KEY to an sk-prefixed local secret before starting LiteLLM."
}

if (-not $MasterKey.StartsWith("sk-")) {
    throw "LiteLLM master key should start with sk- so Claude Code can send it as a bearer token."
}

$env:LITELLM_MASTER_KEY = $MasterKey
$env:CLAUDE_LITELLM_CONFIG = $ConfigPath

if ($ChatGptTokenDir) {
    $env:CHATGPT_TOKEN_DIR = $ChatGptTokenDir
} elseif (-not $env:CHATGPT_TOKEN_DIR) {
    $env:CHATGPT_TOKEN_DIR = Join-Path $env:USERPROFILE ".config\litellm\chatgpt"
}

if (-not $env:CHATGPT_AUTH_FILE) {
    $env:CHATGPT_AUTH_FILE = "auth.json"
}

Write-Host "[litellm] config=$ConfigPath host=$BindHost port=$Port"
Write-Host "[litellm] ChatGPT token dir=$env:CHATGPT_TOKEN_DIR"
Write-Host "[litellm] startup may print a ChatGPT device-code login URL if no token exists"
Write-Host ""
Write-Host "[claude client env]"
Write-Host "  ANTHROPIC_BASE_URL=http://localhost:$Port"
Write-Host "  ANTHROPIC_MODEL=claude-codex-gpt-5-6"
Write-Host "  ANTHROPIC_CUSTOM_HEADERS=x-litellm-api-key: Bearer <LITELLM_MASTER_KEY>"
Write-Host "  CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1"
Write-Host "  ANTHROPIC_DEFAULT_OPUS_MODEL=claude-codex-gpt-5-6"
Write-Host "  ANTHROPIC_DEFAULT_OPUS_MODEL_NAME=Codex GPT-5.6 Sol via LiteLLM"
Write-Host "  ANTHROPIC_DEFAULT_OPUS_MODEL_DESCRIPTION=Agent tool opus alias routed to ChatGPT/Codex GPT-5.6 Sol via LiteLLM"
Write-Host "  ANTHROPIC_DEFAULT_OPUS_MODEL_SUPPORTED_CAPABILITIES=effort,xhigh_effort,max_effort,thinking,adaptive_thinking,interleaved_thinking"
Write-Host "  ANTHROPIC_DEFAULT_SONNET_MODEL=claude-sonnet-5"
Write-Host "  ANTHROPIC_DEFAULT_SONNET_MODEL_NAME=Sonnet 5 via LiteLLM"
Write-Host "  ANTHROPIC_DEFAULT_SONNET_MODEL_DESCRIPTION=Claude Max subscription Sonnet via LiteLLM"
Write-Host "  ANTHROPIC_DEFAULT_SONNET_MODEL_SUPPORTED_CAPABILITIES=effort,xhigh_effort,max_effort,thinking,adaptive_thinking,interleaved_thinking"
Write-Host "  ANTHROPIC_DEFAULT_HAIKU_MODEL=claude-haiku-4-5-20251001"
Write-Host "  ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME=Haiku 4.5 via LiteLLM"
Write-Host "  ANTHROPIC_DEFAULT_HAIKU_MODEL_DESCRIPTION=Claude Max subscription Haiku via LiteLLM"
Write-Host "  ANTHROPIC_CUSTOM_MODEL_OPTION=claude-codex-gpt-5-6"
Write-Host "  ANTHROPIC_CUSTOM_MODEL_OPTION_NAME=Codex GPT-5.6 Sol via LiteLLM"
Write-Host "  ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION=ChatGPT/Codex subscription model"
Write-Host "  ANTHROPIC_CUSTOM_MODEL_OPTION_SUPPORTED_CAPABILITIES=effort,xhigh_effort,max_effort,thinking,adaptive_thinking,interleaved_thinking"
Write-Host ""
Write-Host "[additional gateway discovery aliases]"
Write-Host "  claude-opus-4-6"
Write-Host "  claude-opus-4-7"
Write-Host "  claude-opus-4-8"
Write-Host "  claude-fable-5"
Write-Host "  claude-codex-gpt-5-5"

$ClientOnlyEnvNames = @(
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_CUSTOM_HEADERS",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL_NAME",
    "ANTHROPIC_DEFAULT_OPUS_MODEL_DESCRIPTION",
    "ANTHROPIC_DEFAULT_OPUS_MODEL_SUPPORTED_CAPABILITIES",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL_NAME",
    "ANTHROPIC_DEFAULT_SONNET_MODEL_DESCRIPTION",
    "ANTHROPIC_DEFAULT_SONNET_MODEL_SUPPORTED_CAPABILITIES",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL_DESCRIPTION",
    "ANTHROPIC_CUSTOM_MODEL_OPTION",
    "ANTHROPIC_CUSTOM_MODEL_OPTION_NAME",
    "ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION",
    "ANTHROPIC_CUSTOM_MODEL_OPTION_SUPPORTED_CAPABILITIES",
    "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"
)

$SavedClientOnlyEnv = @{}
foreach ($Name in $ClientOnlyEnvNames) {
    $Value = [Environment]::GetEnvironmentVariable($Name, "Process")
    if ($null -ne $Value) {
        $SavedClientOnlyEnv[$Name] = $Value
        [Environment]::SetEnvironmentVariable($Name, $null, "Process")
    }
}

if ($SavedClientOnlyEnv.Count -gt 0) {
    Write-Host ""
    Write-Host "[litellm] cleared client-only Anthropic env before launching gateway:"
    foreach ($Name in ($SavedClientOnlyEnv.Keys | Sort-Object)) {
        Write-Host "  $Name"
    }
}

$ExitCode = 0
try {
    litellm --config $ConfigPath --host $BindHost --port $Port
    $ExitCode = $LASTEXITCODE
} finally {
    foreach ($Name in $ClientOnlyEnvNames) {
        if ($SavedClientOnlyEnv.ContainsKey($Name)) {
            [Environment]::SetEnvironmentVariable(
                $Name,
                [string]$SavedClientOnlyEnv[$Name],
                "Process"
            )
        } else {
            [Environment]::SetEnvironmentVariable($Name, $null, "Process")
        }
    }
}

exit $ExitCode
