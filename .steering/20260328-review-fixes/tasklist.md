# タスクリスト: レビュー指摘事項の修正

## 実装タスク
- [x] C-02: `_sanitize_revision` に制御文字除去 + XMLデリミタ (`<revision>`) 追加
- [x] C-04: `visualization.py` の `critic_scores` 空リスト防御 (三項式でフォールバック)
- [x] C-05: `tests/test_main.py` 新規作成 (20テスト: parse_args, save_diary, run_pipeline, exit codes)
- [x] W-01: `MemoryManager.__init__` docstring 追加
- [x] W-02: `validate_scenario` 重複バリデーション削除 (コメントに変更理由記載)
- [x] W-03: `visualization.py` フォント検索失敗時の警告ログ追加
- [x] W-04: actor.py / critic.py のセクション参照修正 (SS → §)
- [x] W-05: config.py の Field(description) 追加 (VetoCaps, CriticWeights, StateTransitionConfig)
- [x] W-06: `run_single_day` docstring に `prev_endings` 引数追加
- [x] W-07: `CriticLog.save` docstring に追記モード副作用明記
- [x] W-08: `output_dir` パストラバーサル検証追加 (`Path.relative_to()` 使用)
- [x] W-09: tests/ の ruff 修正 (import順序, 未使用import, 行長超過, 全角括弧)
- [x] C-03→W: actor.py の `dict[str, Any]` → `dict[str, object]` + `cast()` に統一

## テストタスク
- [x] 全テスト Pass 確認 (342 passed in 0.90s)
- [x] ruff check csdg/ tests/ → All checks passed!
- [x] ruff format --check → 29 files already formatted
- [x] mypy csdg/ --strict → Success: no issues found in 15 source files

## 再レビュー
- [x] code-reviewer による修正確認レビュー完了
- [x] W-A (startswith → relative_to) 指摘を反映済み
- [x] W-B (test_dry_run デッドコード削除) 反映済み
