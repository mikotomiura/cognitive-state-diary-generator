# タスクリスト: Best-of-N last-write-wins バグ修正

## 実装タスク
- [x] pipeline.py の success path を確認し、バグ箇所を特定
- [x] `tests/test_pipeline.py` にボーナス再試行 Best-of-N テストを追加 (Red → confirmed fail)
- [x] `csdg/engine/pipeline.py` の success path を修正 (Green)

## テストタスク
- [x] `pytest tests/test_pipeline.py::TestBestOfN::test_bonus_structural_retry_best_of_n` Pass
- [x] `pytest tests/ -x -q` 520 passed — リグレッションなし
- [x] `mypy csdg/ --strict` — No issues
- [x] `ruff check csdg/` — All checks passed

## ドキュメント更新
- [x] `.steering/` 作業記録 (requirement.md, design.md, tasklist.md)
