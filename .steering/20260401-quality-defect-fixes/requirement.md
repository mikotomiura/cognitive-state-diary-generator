# 要件定義: 品質欠陥6件修正

## 背景
quality_report.py による品質分析とテキスト精読で6件の品質問題が発見された。
別エージェントが advice.md に修正案を出力済み。本タスクではその案を精査した上で実装する。

## 実装内容
- P0-2: Veto 無効化バグ修正 (critic.py)
- P0-1: Day 間冒頭テキスト重複チェック追加 (pipeline.py, actor.py, critic.py)
- P1-1: 書き出しパターン分類精度改善 (pipeline.py)
- P1-2: Temperature Decay 不発修正 (pipeline.py)
- P2-2: 余韻パターン分類精度改善 (pipeline.py)
- P2-1: 高インパクト日文体ガイダンス (Prompt_Generator.md)

## 受け入れ条件
- [x] 全テスト Pass (pytest)
- [x] 型チェック Pass (mypy --strict)
- [x] リンター Pass (ruff)
- [x] 新規テスト追加

## 影響範囲
csdg/engine/critic.py, csdg/engine/pipeline.py, csdg/engine/actor.py, prompts/Prompt_Generator.md
