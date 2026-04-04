# タスクリスト: フック強化 + Critic診断軸追加

## 実装タスク
- [x] 1. prompts/Prompt_Generator.md に前日接続・フック・セルフチェックセクション追加
- [x] 2. prompts/Prompt_Critic.md に hook_strength 評価指示追加
- [x] 3. csdg/schemas.py の CriticScore に hook_strength フィールド追加
- [x] 4. csdg/engine/actor.py に prev_day_ending パラメータ追加
- [x] 5. csdg/engine/pipeline.py で prev_day_ending の収集・注入
- [x] 6. csdg/engine/critic.py で hook_strength 転送

## テストタスク
- [x] 7. tests/test_schemas.py に hook_strength テスト追加
- [x] 8. tests/test_critic.py に judge ignores hook_strength テスト追加
- [x] 9. tests/test_actor.py に prev_day_ending 注入テスト追加
- [x] 10. 全テスト実行・mypy・ruff 確認

## 検証結果
- pytest: 513/513 Pass (0.94s)
- mypy --strict: 0 errors
- ruff check: All checks passed
- ruff format: All formatted
