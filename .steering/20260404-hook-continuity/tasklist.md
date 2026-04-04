# タスクリスト: フック連続性強化 (v2.1)

## 実装タスク
- [x] 1. Prompt_Generator.md にフック回収義務・再帰性・1つ限定を追加
- [x] 2. Prompt_Critic.md に prev_day_ending プレースホルダ + フック未回収検知を追加
- [x] 3. critic.py: LLMJudge/CriticPipeline/Critic に prev_day_ending を伝搬
- [x] 4. pipeline.py: evaluate_full() に prev_day_ending を渡す

## テストタスク
- [x] 5. tests/test_critic.py に prev_day_ending 転送テスト追加 (2件)
- [x] 6. 全テスト実行・mypy・ruff 確認

## 検証結果
- pytest: 515/515 Pass (0.98s)
- mypy --strict: 0 errors
- ruff check: All checks passed
- ruff format: All formatted
