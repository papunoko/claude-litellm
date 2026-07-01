# Multi-Model Review Report

作成日: 2026-07-02  
対象: https://github.com/papunoko/claude-litellm

このメモは、Claude Code + LiteLLM gateway 構成に対して、複数モデルで試験的にレビュー workflow を回したときの参考資料です。公開用に、ローカル filesystem path、workflow ID、一時出力 path、個人アカウント名は削っています。

## 実行概要

dynamic workflow でコードレビューとモデル評判調査を混ぜて実行しました。

- Agent 数: 7
- Duration: 約50分
- 構成: 6並列 agent + synthesis
- 観点: architecture / security / test coverage / API compatibility / adversarial bug hunt

self-reported model や workflow journal は routing telemetry ではありません。実際にどの backend が応答したかを暗号学的に証明するものではなく、あくまでレビュー試行の記録として扱います。

## モデル割り振り

| モデル | 割り当て | 期待した役割 |
|---|---|---|
| Opus 4.8 xhigh | architecture / security review、最終 synthesis | 広い文脈理解、運用リスク、認証境界 |
| Sonnet 5 | code quality / test coverage review | 実装確認、テスト不足、日常的な保守観点 |
| Codex GPT-5.5 xhigh | adversarial bug hunt / API compatibility | schema-level bug、edge case、別 vendor 目線の検証 |

## 総合所感

この repo は、個人ローカル用途の Claude Code gateway としてはよく整理されています。Anthropic Messages API と OpenAI Responses API の差分を callback に閉じ込め、Claude / Codex を同じ Claude Code UI から切り替えるための挙動をテストで固定しています。

一方で、公開 repo としては「ローカル専用」を実装で強制する必要がありました。特に、gateway bind address と master key の扱いは、README で注意するだけでは弱いです。

## 採用した修正

### 1. gateway を localhost bind に固定

起動スクリプトに `-BindHost` を追加し、既定を `127.0.0.1` にしました。

```powershell
.\scripts\start-litellm-max-codex-gateway.ps1 -Port 4000
```

既定では `127.0.0.1:4000` だけで listen します。別 host に bind する場合は、利用者が明示的に `-BindHost` を指定します。

### 2. 固定 master key を廃止

公開済みの固定値を既定値として持つのは危険なので、起動時に `-MasterKey` または `LITELLM_MASTER_KEY` を必須にしました。

```powershell
$env:LITELLM_MASTER_KEY = "sk-local-" + [guid]::NewGuid().ToString("N")
.\scripts\start-litellm-max-codex-gateway.ps1 -Port 4000
```

`examples/claude-code-settings.json` と README では、実値ではなく `<LITELLM_MASTER_KEY>` placeholder を使います。

### 3. forced web_search tool_choice を Responses API 用に変換

LiteLLM 1.89.4 の Responses adapter は、Anthropic 側の forced tool choice:

```json
{"type": "tool", "name": "web_search"}
```

を OpenAI Responses の function tool choice に変換します。`web_search` は built-in tool なので、callback 側で次の形に読み替えるようにしました。

```json
{"type": "web_search"}
```

regression test も追加し、Anthropic `web_search_*` tool と forced `tool_choice` が OpenAI `web_search` payload になることを固定しています。

## 採用しなかった指摘

### blocked_domains は OpenAI Responses 側でもサポートされている

レビュー中に「Anthropic `blocked_domains` を OpenAI Responses `web_search` filters に渡すと壊れるのでは」という指摘がありました。

ただし、2026-07-02 時点の OpenAI Web Search docs では、Responses API の `web_search` tool の `filters` に `allowed_domains` と `blocked_domains` の両方を設定できると説明されています。

参考: https://developers.openai.com/api/docs/guides/tools-web-search

そのため、この指摘は採用しませんでした。現状の `allowed_domains` / `blocked_domains` 変換は維持しています。

## 残タスク候補

### OAuth header 分離の振る舞いテスト

README では Claude OAuth `Authorization` header は Claude 系 alias にだけ forward し、`chatgpt/` には forward しないと説明しています。現状は YAML shape の確認が中心なので、将来的には actual provider request に `Authorization` が漏れないことを mock / integration test で検証したいです。

### streaming web_search citation

non-streaming path は OpenAI annotation から URL citation / source title を Anthropic 風に戻します。一方で streaming path は source title / citation の再構成が限定的です。調査用途を重視するなら、streaming event の annotation 蓄積か、README での制限明記が必要です。

### async_pre_request_hook の直接テスト

既存テストは `async_pre_call_hook` の直接駆動が中心です。LiteLLM lifecycle の別 entry point である `async_pre_request_hook` も直接テストして、hook 間の regression を検出できるようにしたいです。

### LiteLLM private internals guard

この callback は LiteLLM 1.89.4 の private internals に依存します。patch 対象 symbol が消えた場合は fail-fast しますが、signature や semantics の drift は検出しきれません。version guard や smoke test を足す余地があります。

## モデル別レビュー挙動

### Opus 4.8

この workflow では、gateway bind + fixed key という operational exploit chain を拾うなど、広い設計・運用リスクの検出には有用でした。

ただし、日本語圏の Claude Code 実利用では Opus 4.8 の tool-call corruption、長い session での不安定さ、Windows 周りの崩れ方への不満が強く、ベンチマーク評価ほど安心して常用できるモデルではないという見方があります。英語圏ベンチが良いため捨てにくいが、実運用ではかなり慎重に扱うべきモデル、という位置づけです。

### Sonnet 5

Sonnet 5 は、日常 coding / test review / verification-oriented task の主力候補として見えました。

日本語圏の短評としては「悪くない」「バグっていない 4.8 という感じ」という見方があり、Opus 4.8 の不安定さを避けつつ、かなり近い実用感を得るモデルとして期待できます。最難関の architecture / security synthesis は Opus 系に任せる余地がありますが、普段使いでは Sonnet 5 を中心にするのが現実的です。

### Codex GPT-5.5

Codex GPT-5.5 は、遅い一方で API schema / edge case を深く読む用途に向いていました。今回も forced `web_search` tool choice のような vendor boundary の bug を拾うのに役立ちました。

常用チャットモデルというより、独立した cross-vendor reviewer / adversarial bug hunter として使うのが費用対効果の良い使い方です。

## Caveats

- この report は一回の試行結果であり、統計的なモデル評価ではありません。
- モデル別所感には、workflow 出力、公開情報、ユーザー提供の短評からの推定が含まれます。
- 実 OpenAI / Anthropic endpoint への全パターン再現試験は行っていません。
- 最新の API schema は変わり得るため、特に `web_search` と LiteLLM private internals は更新時に再検証が必要です。
