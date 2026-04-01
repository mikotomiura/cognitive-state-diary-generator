# 要件定義: アーキテクチャ改善 (循環依存解消 + ERRE設計文書 + 品質サマリ)

## 背景
advice.md に記載された3つの改善案を検証し、全て有効と判断。

## 実装内容
1. **P0:** `constants.py` 新設による循環依存解消
2. **P1:** ERRE 設計文書の作成
3. **P1:** 品質サマリスクリプトの作成
4. **付随:** ドキュメント更新 (repository-structure.md, architecture.md)

## 受け入れ条件
- [ ] actor.py から pipeline.py への直接インポートがないこと
- [ ] 重複定数が constants.py に集約されていること
- [ ] 全既存テストがパスすること
- [ ] erre-design.md が glossary.md/architecture.md と整合していること
- [ ] quality_report.py が generation_log.json を正しく分析できること

## 影響範囲
- csdg/engine/actor.py, pipeline.py, constants.py (新規)
- docs/architecture.md, repository-structure.md, erre-design.md (新規)
- scripts/quality_report.py (新規)
- tests/test_pipeline.py
