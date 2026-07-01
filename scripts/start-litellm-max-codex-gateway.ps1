# Start LiteLLM gateway with both Claude Max OAuth and ChatGPT/Codex
# subscription models exposed to Claude Code.
param(
    [int]$Port = 4000,
    [string]$MasterKey = "sk-litellm-local-master-key",
    [string]$Config = "litellm_config.max-codex-subscriptions.yaml",
    [string]$ChatGptTokenDir = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$ConfigPath = (Resolve-Path $Config).Path

Get-Command litellm -ErrorAction Stop | Out-Null

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

Write-Host "[litellm] config=$ConfigPath port=$Port"
Write-Host "[litellm] ChatGPT token dir=$env:CHATGPT_TOKEN_DIR"
Write-Host "[litellm] startup may print a ChatGPT device-code login URL if no token exists"
Write-Host ""
Write-Host "[claude client env]"
Write-Host "  ANTHROPIC_BASE_URL=http://localhost:$Port"
Write-Host "  ANTHROPIC_MODEL=claude-codex-gpt-5-5"
Write-Host "  ANTHROPIC_CUSTOM_HEADERS=x-litellm-api-key: Bearer $MasterKey"
Write-Host "  CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1"
Write-Host "  ANTHROPIC_DEFAULT_OPUS_MODEL=claude-opus-4-8"
Write-Host "  ANTHROPIC_DEFAULT_OPUS_MODEL_NAME=Opus 4.8 via LiteLLM"
Write-Host "  ANTHROPIC_DEFAULT_OPUS_MODEL_DESCRIPTION=Claude Max subscription Opus via LiteLLM"
Write-Host "  ANTHROPIC_DEFAULT_OPUS_MODEL_SUPPORTED_CAPABILITIES=effort,xhigh_effort,max_effort,thinking,adaptive_thinking,interleaved_thinking"
Write-Host "  ANTHROPIC_DEFAULT_SONNET_MODEL=claude-sonnet-5"
Write-Host "  ANTHROPIC_DEFAULT_SONNET_MODEL_NAME=Sonnet 5 via LiteLLM"
Write-Host "  ANTHROPIC_DEFAULT_SONNET_MODEL_DESCRIPTION=Claude Max subscription Sonnet via LiteLLM"
Write-Host "  ANTHROPIC_DEFAULT_SONNET_MODEL_SUPPORTED_CAPABILITIES=effort,xhigh_effort,max_effort,thinking,adaptive_thinking,interleaved_thinking"
Write-Host "  ANTHROPIC_DEFAULT_HAIKU_MODEL=claude-haiku-4-5-20251001"
Write-Host "  ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME=Haiku 4.5 via LiteLLM"
Write-Host "  ANTHROPIC_DEFAULT_HAIKU_MODEL_DESCRIPTION=Claude Max subscription Haiku via LiteLLM"
Write-Host "  ANTHROPIC_CUSTOM_MODEL_OPTION=claude-codex-gpt-5-5"
Write-Host "  ANTHROPIC_CUSTOM_MODEL_OPTION_NAME=Codex GPT-5.5 via LiteLLM"
Write-Host "  ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION=ChatGPT/Codex subscription model"
Write-Host "  ANTHROPIC_CUSTOM_MODEL_OPTION_SUPPORTED_CAPABILITIES=effort,xhigh_effort,max_effort,thinking,adaptive_thinking,interleaved_thinking"
Write-Host ""
Write-Host "[additional gateway discovery aliases]"
Write-Host "  claude-opus-4-6"
Write-Host "  claude-opus-4-7"

litellm --config $ConfigPath --port $Port
