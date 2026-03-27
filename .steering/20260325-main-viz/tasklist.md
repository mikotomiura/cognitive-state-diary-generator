# タスクリスト: main.py + visualization.py

## 実装タスク
- [x] csdg/main.py: parse_args, run_pipeline, save_diary, main
- [x] csdg/visualization.py: generate_state_trajectory

## テストタスク
- [x] tests/test_visualization.py: グラフ生成、ファイル出力、リソース解放 (4件)

## 検証タスク
- [x] python -m csdg.main --dry-run 正常終了 (exit code 0)
- [x] pytest tests/ -v 全181件 Pass
- [x] mypy --strict エラー 0
- [x] ruff check / ruff format エラー 0

## 追加: pipeline.py レビュー指摘修正
- [x] C-01: マジックナンバーをモジュール定数に抽出
- [x] C-02: パイプライン中断ログを logger.critical に変更
- [x] C-03: フォールバックログを logger.warning に変更
- [x] C-04: 空テスト test_sliding_window_at_day5 を有意なテストに置換
- [x] W-03: ValidationError の例外詳細をログに含める
- [x] W-04: _make_pass_score / _make_reject_score に docstring 追加
