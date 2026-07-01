# Claude Code LiteLLM Gateway for Claude Max + Codex GPT-5.5

Claude Code から、同じ LiteLLM gateway 経由で次の 2 系統を切り替えて使うための最小構成です。

- Claude Max / Pro subscription の Claude モデル
- ChatGPT/Codex subscription の `gpt-5.5`

Claude Code は Anthropic Messages 互換 endpoint として `http://localhost:4000` に接続します。LiteLLM 側で Claude 風 alias を受け、Claude 系は Anthropic pass-through、Codex 系は LiteLLM 公式 `chatgpt/` provider の Responses API 経路へ流します。

## モデル

```text
claude-opus-4-6                 -> anthropic/claude-opus-4-6
claude-opus-4-7                 -> anthropic/claude-opus-4-7
claude-opus-4-8                 -> anthropic/claude-opus-4-8
claude-fable-5                  -> anthropic/claude-fable-5
claude-sonnet-5                 -> anthropic/claude-sonnet-5
claude-haiku-4-5-20251001       -> anthropic/claude-haiku-4-5-20251001
claude-codex-gpt-5-5            -> chatgpt/gpt-5.5, reasoning.effort=medium
```

`claude-codex-gpt-5-5` が `claude-` で始まるのは、Claude Code の gateway model discovery / `/model` picker に出しやすくするためです。

## 検証済み前提環境

この repo は次の環境で検証しています。

```text
OS          : Microsoft Windows 11 Pro 64-bit, version 10.0.26200
PowerShell  : Windows PowerShell 5.1.26100.7920
Claude Code : 2.1.197
LiteLLM     : 1.89.4, uv tool install "litellm[proxy]"
Gateway     : LiteLLM proxy on http://localhost:4000
```

依存している API / provider:

- Claude Code gateway model discovery
- Anthropic Messages API: `/v1/messages`
- Anthropic Models API: `/v1/models`
- OpenAI Responses API: `/v1/responses`
- OpenAI hosted web search tool: `web_search`
- LiteLLM official ChatGPT provider: `chatgpt/`
- LiteLLM Anthropic-compatible proxy endpoint: `/v1/messages`

関連 docs:

- Claude Code model configuration: <https://docs.anthropic.com/en/docs/claude-code/model-config>
- Claude model overview / model IDs: <https://docs.anthropic.com/en/docs/about-claude/models/overview>
- Anthropic Messages API: <https://docs.anthropic.com/en/api/messages>
- OpenAI Responses API: <https://developers.openai.com/api/reference/responses/create>
- OpenAI web search tool: <https://developers.openai.com/api/docs/guides/tools-web-search>
- LiteLLM ChatGPT provider: <https://docs.litellm.ai/docs/providers/chatgpt>

## インストール

```powershell
uv tool install "litellm[proxy]"
```

既に LiteLLM がある場合は、公式 `chatgpt/` provider が入っている版へ更新します。

```powershell
uv tool upgrade litellm
```

## Gateway 起動

```powershell
$env:LITELLM_MASTER_KEY = "sk-local-<stable-secret>"
$env:LITELLM_MASTER_KEY
.\scripts\start-litellm-max-codex-gateway.ps1 -Port 4000
```

`<stable-secret>` は一度だけ作り、gateway 起動時の `LITELLM_MASTER_KEY` と `~/.claude/settings.json` の `ANTHROPIC_CUSTOM_HEADERS` で同じ値を使います。値を変えた場合は Claude Code 側の設定も同じ値に更新してください。

起動スクリプトは以下を設定します。

- `LITELLM_MASTER_KEY`
- `CLAUDE_LITELLM_CONFIG`
- `CHATGPT_TOKEN_DIR`
- `CHATGPT_AUTH_FILE`

`chatgpt/` provider の初回利用時は、LiteLLM が ChatGPT device-code login URL を表示することがあります。ChatGPT/Codex subscription のあるアカウントでログインしてください。既定の保存先は以下です。

```text
%USERPROFILE%\.config\litellm\chatgpt\auth.json
```

この `auth.json` は絶対に commit しないでください。

gateway は既定で `127.0.0.1:4000` にだけ bind します。別 host に bind する場合だけ `-BindHost` を明示してください。

## Claude Code 側設定

手元の `~/.claude/settings.json` の設定例は [examples/claude-code-settings.json](examples/claude-code-settings.json) にあります。
普段使いでは、ここで使う環境変数は shell profile ではなく `~/.claude/settings.json` の `env` に書いておくのがおすすめです。`<LITELLM_MASTER_KEY>` は gateway 起動時に使う stable secret と同じ値へ置き換えてください。Claude Code の新規セッションごとに同じ gateway 設定が読み込まれ、LiteLLM の master key と `ANTHROPIC_CUSTOM_HEADERS` のずれも起きにくくなります。

PowerShell で一時的に試すなら、最小形は次の通りです。

```powershell
Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:ANTHROPIC_AUTH_TOKEN -ErrorAction SilentlyContinue

$env:ANTHROPIC_BASE_URL = "http://localhost:4000"
$env:ANTHROPIC_CUSTOM_HEADERS = "x-litellm-api-key: Bearer $env:LITELLM_MASTER_KEY"
$env:CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY = "1"

$env:ANTHROPIC_DEFAULT_OPUS_MODEL = "claude-opus-4-8"
$env:ANTHROPIC_DEFAULT_SONNET_MODEL = "claude-sonnet-5"
$env:ANTHROPIC_DEFAULT_HAIKU_MODEL = "claude-haiku-4-5-20251001"

$env:ANTHROPIC_CUSTOM_MODEL_OPTION = "claude-codex-gpt-5-5"
$env:ANTHROPIC_CUSTOM_MODEL_OPTION_NAME = "Codex GPT-5.5 via LiteLLM"
$env:ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION = "ChatGPT/Codex subscription model"
$env:ANTHROPIC_CUSTOM_MODEL_OPTION_SUPPORTED_CAPABILITIES = "effort,xhigh_effort,max_effort,thinking,adaptive_thinking,interleaved_thinking"

$env:ANTHROPIC_MODEL = "claude-codex-gpt-5-5"
claude
```

Claude Code 内では `/model` で Claude alias と Codex alias を切り替えます。Codex alias の既定 effort は `medium` です。必要な時だけ `/effort high` や `/effort max` を使ってください。gateway は `/effort max` を OpenAI Responses の `reasoning.effort=xhigh` に読み替えます。

`claude-opus-4-6`、`claude-opus-4-7`、`claude-fable-5` は、`ANTHROPIC_DEFAULT_OPUS_MODEL` にはしません。既定 Opus は `claude-opus-4-8` のままにし、モデル多様性や回帰確認が必要な時に gateway model discovery / `/model claude-opus-4-6` / `/model claude-opus-4-7` / `/model claude-fable-5` で選びます。

## callback がやっていること

`litellm_callbacks/chatgpt_anthropic_messages.py` は、Claude Code の Anthropic Messages request を保ったまま `chatgpt/` provider へ流すためのローカル callback です。

- LiteLLM の Anthropic Messages -> Responses 経路を `chatgpt/` provider にも有効化する
- Anthropic の top-level `system` を Responses の `instructions` に写す
- Codex alias の `/effort` を Responses `reasoning.effort` に写す
- Claude / Codex を同じ会話で切り替えた時に残る空 `thinking` block を落とす
- Anthropic `web_search_*` tool を OpenAI Responses `web_search` tool へ変換する
- OpenAI `web_search_call` / `url_citation` を Anthropic の `server_tool_use` / `web_search_tool_result` / `citations` へ戻す
- Claude の system prompt 末尾に、gateway で使える非 Claude alias を XML 風 note として追記する

## 注意点

- gateway はローカル利用前提です。外部ネットワークへ公開しないでください。
- OAuth token、`auth.json`、`.env`、API key、setup token は commit しないでください。
- Claude Code が gateway へ送る Claude OAuth `Authorization` header は、Claude 系 alias にだけ forward します。`chatgpt/` には forward しません。
- ChatGPT/Codex 側の token は LiteLLM `chatgpt/` provider がローカル token directory から読みます。
- OpenAI と Anthropic の hosted web search 結果形式は完全一致しません。実用上の source / citation は戻しますが、Anthropic の encrypted citation fields は OpenAI 出力から再生成できないため空になります。

## テスト

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test-litellm-max-codex-gateway.ps1
```

成功すると `OK` が出ます。
