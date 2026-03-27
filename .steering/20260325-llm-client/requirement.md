# 要件定義: LLMClient 抽象インターフェースと OpenAI 実装

## 背景
パイプラインの各 Phase は LLM API を呼び出す必要がある。
将来的に OpenAI 以外の LLM（Anthropic Claude 等）に切り替える可能性を考慮し、
LLM 呼び出しを抽象化した `LLMClient` インターフェースと、その OpenAI 実装を提供する。

## 実装内容
1. `LLMClient` 抽象基底クラス — `generate_structured()` と `generate_text()` の2メソッド
2. `OpenAIClient` — `openai` ライブラリの `AsyncOpenAI` を使用した具体実装

## 受け入れ条件
- [ ] `LLMClient` 抽象クラスが定義されている
- [ ] `OpenAIClient` が `LLMClient` を継承して実装されている
- [ ] mypy --strict でエラー 0
- [ ] ruff check でエラー 0
- [ ] OpenAIClient のインスタンス化テストが存在し Pass する

## 影響範囲
- `csdg/engine/llm_client.py` — 新規作成
- `tests/test_llm_client.py` — 新規作成
