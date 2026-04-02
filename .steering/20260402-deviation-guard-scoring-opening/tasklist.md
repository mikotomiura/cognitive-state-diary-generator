# タスクリスト: Deviation Guard + Scoring 最適化 + Opening 検出精緻化

## 実装タスク
- [ ] A: pipeline.py に Phase 1 deviation guard を実装
- [ ] B: critic.py Layer 1 の emotional_plausibility 閾値を最適化
- [ ] B: critic.py Layer 2 の emotional_plausibility 閾値を最適化
- [ ] C: pipeline.py _detect_opening_pattern に「会話の残響」検出を追加

## テストタスク
- [ ] test_pipeline.py に deviation guard テストを追加
- [ ] test_pipeline.py に opening 検出テストを追加
- [ ] test_critic.py の Layer 1/2 閾値テストを更新

## 検証タスク
- [ ] mypy --strict 通過
- [ ] ruff check 通過
- [ ] pytest 全件 Pass
- [ ] パイプライン再実行で fallback 0, emotional_plausibility 改善, opening 7/7
