# 要件定義: OpenAI → Anthropic Claude API 移行

## 背景
コスト・品質の再検討により、LLM バックエンドを OpenAI (gpt-4o) から Anthropic Claude API (claude-sonnet-4-20250514) に変更する。

## 実装内容
1. pyproject.toml: openai → anthropic 依存関係変更
2. .env.example: Anthropic 用に更新
3. config.py: デフォルト値を Claude に変更
4. llm_client.py: OpenAIClient → AnthropicClient (tool_use パターン)
5. main.py: AnthropicClient に差し替え
6. テスト更新

## 受け入れ条件
- [ ] openai が pyproject.toml に含まれていないこと
- [ ] AnthropicClient が tool_use パターンで構造化出力を実装
- [ ] system パラメータが正しく使われている
- [ ] uv sync 成功
- [ ] 全テスト Pass
- [ ] mypy --strict, ruff check エラー 0
