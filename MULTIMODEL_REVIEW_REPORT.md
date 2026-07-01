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

## 日本語圏モデル評価メモ

`gens.txt` にあった Sonnet 5 / Opus 4.7-4.8 / GPT-5.5 評価を、公開用にサニタイズして整理したものです。個別の X アカウント名、長い直接引用、ローカル調査ログは載せず、Qiita / Zenn / note / 企業テックブログ / X 上の短評から見えた評価構造だけを残しています。

### Sonnet 5

日本語圏での Sonnet 5 の初期評判は、単純な「Opus 4.8 に迫る高性能モデル」というより、Opus 4.7 / 4.8 で起きていた日本語品質と Claude Code 挙動への不満を背景にした相対評価として読む必要があります。

象徴的には「悪くない」「バグっていない 4.8」という短評に近い受け止めです。つまり、Opus 4.8 級の設計判断や推論力そのものを完全に超えたというより、Opus 4.8 で感じられた日本語の変さ、tool-call の不安定さ、会話の温度感の薄さが少ないため、実用上は安心して投げやすい、という評価です。

日本語品質については、Sonnet 3.5 / 4.x 系にあった自然な日本語が戻った、長文でも文体が崩れにくい、会話していて読みやすい、という声が目立ちました。一方で、謎の英語混入や誤字が完全に消えたわけではなく、「Opus 4.7 / 4.8 よりはかなり良いが万能ではない」という温度感です。

Claude Code / agent 用途では、長いタスクで迷子になりにくい、テスト実行と修正を自走しやすい、サブエージェントや executor として放りやすい、という評価が多くありました。特に multi-agent 構成では、Sonnet 5 を executor、Opus 系を advisor / synthesis に置く分担が現実的です。Sonnet 5 を常に high / xhigh effort で回すより、低〜中 effort の Sonnet 5 に作業を任せ、必要な判断だけ Opus に渡す方が費用対効果はよい、という見方です。

MAX plan 利用者にとっては、Opus を自由に呼べるため Sonnet 5 の存在意義がやや薄く見える場合があります。それでも、大量の整理、繰り返し作業、下書き、検証、サブエージェント実行などには Sonnet 5 を使う意味があります。Pro plan や API 利用では、Sonnet 5 は日常の主力候補になります。

### Opus 4.7 / Opus 4.8

Sonnet 5 の評価は、Opus 4.7 / 4.8 の日本語圏での不評と切り離せません。日本語話者の間では、Opus 4.6 以前に比べて Opus 4.7 / 4.8 の日本語が不自然、語彙選択が変、翻訳や要約で違和感が出る、入力解釈がずれる、という体感が広く共有されていました。

Claude Code では、tool-call corruption、長い session での挙動の崩れ、Windows 環境での不安定さ、指示していない作業を進める、細かい prompt 作法が効きにくくなる、といった実務上の不満もありました。英語圏ベンチマークでは強く見えても、日本語での対話・文章生成・Claude Code 実運用では、そのまま信頼しにくいという評価です。

一方で、この workflow では Opus 4.8 が gateway bind address と固定 master key の組み合わせを operational risk として拾いました。広い文脈の設計レビュー、認証境界、root-cause analysis、最終 synthesis では依然として強いです。したがって、Opus 4.8 は「常用 executor」ではなく「重い判断を任せる advisor / reviewer」として使う方が安全です。

### GPT-5.5 / Codex

GPT-5.5 / Codex は、日本語圏では Claude と競合する常用チャットモデルというより、別 vendor の検証 seat として使う評価が近いです。遅いが深く読む、repo と schema を粘って見る、edge case を拾う、という方向で価値があります。

日本語文書では、数字や構造化された事実整理、申請書や仕様文の下書きに強いという見方があります。一方で、感情や説得力を要する日本語、文体の自然さ、対話の楽しさでは Claude 系へ戻す分業が多く見られます。Opus 4.7 / 4.8 の日本語劣化でこの分業が崩れていたところを、Sonnet 5 が Claude 側へ引き戻した、というのが `gens.txt` の大きな読みです。

コードレビューでは、今回も forced `web_search` tool choice のような vendor boundary の bug を拾う役に立ちました。Anthropic Messages と OpenAI Responses の schema 差分、tool payload、streaming / non-streaming の戻り値変換など、細部の互換性を見る reviewer として有用です。

### Fable / Mythos 文脈

`gens.txt` では、Fable 5 / Mythos 5 停止の文脈も Sonnet 5 評価に影響していると整理されていました。Fable 5 を「Opus 4.6 の正統進化」と感じた層にとって、Opus 4.7 / 4.8 は薄く冷たい、または不安定に見えやすく、その代替として Sonnet 5 がどこまで使えるかが問われていました。

結論としては、Sonnet 5 は Fable 5 の完全な代替というより、実務 executor としての安定枠です。日本語の勝負文書や難しい設計判断は将来の Fable / Opus 系に期待しつつ、普段の作業を Sonnet 5 に寄せる、という整理が現実的です。

### 日本語圏での使い分け

現時点の使い分けは次のように見るのが自然です。

- Sonnet 5: 日常 coding、テスト修正、下書き、整理、サブエージェント、executor
- Opus 4.8: architecture review、security boundary、root-cause analysis、最終 synthesis
- GPT-5.5 / Codex: adversarial review、schema / API compatibility、別 vendor 視点の bug hunt

この repo の狙いである「Claude Code から Claude Max と Codex subscription model を同じ gateway で切り替える」構成は、この評価構造と相性がよいです。普段は Sonnet 5 / Claude alias、深い別視点レビューは `claude-codex-gpt-5-5`、重い統合判断は Opus alias へ切り替える運用になります。

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
$env:LITELLM_MASTER_KEY = "sk-local-<stable-secret>"
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
