# Claude Code LiteLLM Gateway for Claude Max + Codex GPT-5.5 / GPT-5.6

Claude Code から、同じ LiteLLM gateway 経由で次の 2 系統を切り替えて使うための最小構成です。

- Claude Max / Pro subscription の Claude モデル
- ChatGPT/Codex subscription の `gpt-5.5` / `gpt-5.6-sol`

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
claude-codex-gpt-5-6            -> chatgpt/gpt-5.6-sol, reasoning.effort=medium
```

`claude-codex-gpt-5-*` が `claude-` で始まるのは、Claude Code の gateway model discovery / `/model` picker に出しやすくするためです。

`claude-codex-gpt-5-6` は GPT-5.6 世代のフラッグシップ tier (Sol) を指します。GPT-5.6 は LiteLLM の既存 GPT-5 config family でそのまま動くため、LiteLLM 1.89.4 のままで利用できます（2026-07-11 に `/v1/messages` smoke 確認済み）。token window は Codex subscription surface の実測が取れるまで GPT-5.5 と同じ 272K input / 128K output に pin しています。

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

`Enable-ClaudeLiteLLM` を実行した PowerShell からそのまま gateway を起動しても、起動スクリプトは client 用の `ANTHROPIC_BASE_URL` / `ANTHROPIC_CUSTOM_HEADERS` などを LiteLLM 子プロセスへ渡さないように一時的に退避します。これにより、LiteLLM が `http://localhost:4000/v1/messages` を upstream として叩く自己参照を避けます。

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

$env:ANTHROPIC_CUSTOM_MODEL_OPTION = "claude-codex-gpt-5-6"
$env:ANTHROPIC_CUSTOM_MODEL_OPTION_NAME = "Codex GPT-5.6 Sol via LiteLLM"
$env:ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION = "ChatGPT/Codex subscription model"
$env:ANTHROPIC_CUSTOM_MODEL_OPTION_SUPPORTED_CAPABILITIES = "effort,xhigh_effort,max_effort,thinking,adaptive_thinking,interleaved_thinking"

$env:ANTHROPIC_MODEL = "claude-codex-gpt-5-6"
claude
```

Claude Code 内では `/model` で Claude alias と Codex alias を切り替えます。Codex alias の既定 effort は `medium` です。必要な時だけ `/effort high` や `/effort max` を使ってください。gateway の `/effort max` の扱いはモデル世代で変わります: GPT-5.6 系 alias では `reasoning.effort=max` をそのまま透過し（GPT-5.6 は max を native サポート。2026-07-11 smoke 確認済み）、GPT-5.5 以前の alias では従来どおり `xhigh` へ読み替えます。

`opus` subagent も Codex alias へ向けたい場合は、session-only の shell env だけではなく `~/.claude/settings.json` の `env` にも `ANTHROPIC_BASE_URL` / `ANTHROPIC_CUSTOM_HEADERS` / `ANTHROPIC_DEFAULT_OPUS_MODEL=claude-codex-gpt-5-6`（旧世代を使うなら `claude-codex-gpt-5-5`）を書いておきます。Claude Code の background `Agent` / subagent worker は、親 shell だけに設定した env を引き継がない場合があるためです。

実 Claude Opus を既定の `opus` にしたい場合は `ANTHROPIC_DEFAULT_OPUS_MODEL=claude-opus-4-8` に戻します。`claude-opus-4-6`、`claude-opus-4-7`、`claude-fable-5` は、モデル多様性や回帰確認が必要な時に gateway model discovery / `/model claude-opus-4-6` / `/model claude-opus-4-7` / `/model claude-fable-5` で選びます。

## context window と compaction（長い subagent が落ちる時）

この gateway の `chatgpt/gpt-5.5` 経路（Codex / ChatGPT subscription surface）は **総 400K の context window** として扱うのが安全で、内訳は **入力 272K + 推論/出力 128K** です（`272000 + 128000 = 400000`）。OpenAI API の `gpt-5.5` は別途 1M 級 context として公開されていますが、この repo の既定経路は API key 直叩きではなく subscription 経路なので、ここでは 400K split を pin します。ここを取り違えると、長時間の subagent ターンで次のどちらかが起きます。

- gateway / client が **入力を 400K まで詰められる**と誤認 → Responses 側の実上限 272K を超え、`input tokens exceed ... 272000` 系の 400 が返る。Claude Code の subagent はこの 400 でターンごと死に、親のワークフローも巻き込まれる。
- 逆に window を過小申告（Codex CLI が 400K を 258,400 と表示した既知の不具合と同型）すると、Claude Code が **早すぎる auto-compact** を打ち、goal や制約が落ちて drift する。

この repo では `litellm_config.max-codex-subscriptions.yaml` の `claude-codex-gpt-5-5` に window を明示 pin してあります。

```yaml
  - model_name: claude-codex-gpt-5-5
    model_info:
      mode: responses
      max_input_tokens: 272000   # Codex/ChatGPT subscription 経路の実入力上限
      max_output_tokens: 128000  # 推論 + 出力
      max_tokens: 128000
```

`CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` を使っていれば、Claude Code はこの `model_info` を読んで context 会計と compaction 閾値を合わせられます。値を確認したい時は次で見られます。

```powershell
curl.exe -s -H "x-litellm-api-key: Bearer $env:LITELLM_MASTER_KEY" http://localhost:4000/v1/model/info
```

**運用側の注意（重要）**: メイン会話は auto-compact されますが、Claude Code の **subagent（Task/Agent worker）は基本 compact されず、context を超えると 400 で即死** します。したがって subagent を長く回す設計そのものを避けるのが本筋です。dynamic-workflow skill 側で「subagent の戻り値はメタデータのみ（本文はファイルへ）」「下流に配る土台情報は 70 行以内」「出力行数・トークン上限を必ず指定」を守ると、この 400 はほぼ消えます。詳細は `~/.claude/skills/dynamic-workflow`（`references/failure-modes.md` の context-loss 節、`references/multi-model.md`）を参照。

### Codex CLI 側は既定context / compactionを使う

LiteLLM の `model_info.max_input_tokens` と、Codex CLI の `~/.codex/config.toml` は別の設定です。GPT-5.6 Codex CLIでは、次の手動overrideを既定設定として追加しません。

```toml
# 通常は設定しない
# model_context_window = 272000
# model_auto_compact_token_limit = 240000
```

当初は272K超の料金帯を避ける案として紹介されていましたが、OpenAI Codex/ChatGPTチームの[@thsottiauxによる訂正（2026-07-12）](https://x.com/thsottiaux/status/2076201049086648705)では、Codexの利用枠では270K超に追加課金せず、GPT-5.6 Solの既定context thresholdは調整済みとされています。したがってこのrepoでは、task固有の計測根拠がない限りCodex既定値を使います。

Claude Code→LiteLLM経路では`~/.codex/config.toml`自体を参照しません。そちらの入力会計は、引き続き`litellm_config.max-codex-subscriptions.yaml`の実測済み`max_input_tokens: 272000`で制御します。これはCodex CLIのauto-compaction overrideとは別問題です。

## structured output が崩れる時（最終段の JSON）

structured output は **Codex/ChatGPT 経路で常に失敗するわけではありません**。LiteLLM の Anthropic Messages → Responses adapter は、`output_format` または `output_config.format` の `json_schema` を OpenAI Responses の `text.format`（`strict: true`）へ写します。また Claude Code / Dynamic Workflow 側が `StructuredOutput` tool として schema を表現する場合も、通常 tool/function として Responses 経路へ渡ります。

それでも崩れる主因は、gateway が schema を全部落とすことではなく、次のいずれかです。

- `strict: true` 経路に載る schema が OpenAI strict 互換でない（全 object の `additionalProperties:false`、全 property の `required`、optional は nullable かつ required、root `anyOf` なし等）。
- `StructuredOutput` tool 経路で、モデルが root の一部だけ（例: `items` だけ、`scope` だけ）を tool call して retry を浪費する。
- 出力が長すぎて truncation / parse fallback が起きる。

実務上の回避策:

- **重要な最終 synthesis / structured 段は native Claude（`fable` / 実 Opus）で実行する**。これは structured-output だけでなく、最終判断ノードを Fable に残すという役割分担とも一致します。
- Codex 経路で JSON を返させる時は、schema を OpenAI strict 互換に寄せ、schema を**プロンプト本文にも展開**し、返ってきた JSON を**ワークフロー側で検証 → 不正なら 1 回だけ repair-retry** する。schema opt 単体を唯一の保証にしない。
- 失敗調査では「schema が透過しない」と決め打ちせず、`Structured output provided successfully` と `Output does not match required schema` の両方をログで数える。

ログ実測での失敗軸の切り分け（重要）:

- `Output does not match required schema`（root property 欠落）は **native Claude 側に集中**（実測: opus-4-8=154 / haiku=54、`gpt-5.5`=0）。これは Claude Code の `StructuredOutput` **tool** が root の一部だけを tool call することによる client 側現象で、retry / `[structured-output-enforce]` で最終的に成功へ収束する例が多い。gateway が schema を落としているわけではない。
- `claude-codex-gpt-5-5`（gpt-5.5）側の典型失敗は schema 不一致ではなく、`Write` / `Bash` / `Edit` の **tool 引数 JSON 破損**（`... was called with input that could not be parsed as JSON`）。20〜35KB 級の巨大本文を 1 回の `Write` に詰めた時に頻発し、放置すると `[no visible output]` → `[structured-output-enforce]` の空転で subagent がターン終端に到達しないまま死ぬ。対策は本文の分割書き込みと Filesystem-as-IPC で、schema をいじることではない。

この設計判断は dynamic-workflow skill にも反映済み（`references/schema-sketches.md` の cross-provider 節、`references/multi-model.md`）。

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
