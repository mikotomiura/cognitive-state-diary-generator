# タスクリスト: アーキテクチャ改善

## 実装タスク
- [x] T1-1: constants.py 新規作成
- [x] T1-2: pipeline.py から定数を移動 + インポート修正
- [x] T1-3: actor.py から重複定数削除 + 遅延インポート削除 + インポート修正
- [x] T1-4: テスト追加 (test_pipeline.py に TestConstants クラス)
- [x] T3: quality_report.py 作成
- [x] T2: erre-design.md 作成

## ドキュメント更新
- [x] T4-1: architecture.md 更新
- [x] T4-2: repository-structure.md 更新

## 品質チェック
- [x] pytest tests/ -v (446 passed)
- [x] mypy csdg/ --strict (no issues in 16 files)
- [x] ruff check + format (all passed)
