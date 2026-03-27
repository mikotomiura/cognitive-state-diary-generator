# タスクリスト: OpenAI → Anthropic 移行

## 実装タスク
- [x] pyproject.toml: openai → anthropic>=0.42.0
- [x] .env.example: Anthropic 用に更新
- [x] config.py: デフォルト値変更 (claude-sonnet-4-20250514, api.anthropic.com)
- [x] llm_client.py: AnthropicClient 実装 (tool_use パターン)
- [x] main.py: AnthropicClient に差し替え
- [x] conftest.py: モデル名更新

## テストタスク
- [x] test_llm_client.py: 10件 (抽象クラス3 + 初期化3 + 構造化生成2 + テキスト生成2)
- [x] test_config.py: デフォルト値テスト更新

## 検証タスク
- [x] uv sync 成功 (anthropic==0.86.0 installed, openai removed)
- [x] pytest 全184件 Pass
- [x] mypy --strict エラー 0 (11 source files)
- [x] ruff check エラー 0
- [x] openai 参照ゼロ確認
- [x] dry-run 正常終了
