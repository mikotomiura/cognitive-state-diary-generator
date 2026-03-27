# 要件定義: レビュー指摘事項の修正

## 背景
統合レビュー（2026-03-28）で検出された Critical 4件 + Warning 9件の修正。

## 実装内容

### Critical (マージ前必須)
- C-02: `_sanitize_revision` にデリミタ追加（プロンプトインジェクション防御）
- C-03→W: `dict[str, Any]` → 共有型エイリアスに統一（mypy Pass済みのためWarningに格下げ）
- C-04: `visualization.py` の `critic_scores` 空リスト対策
- C-05: `tests/test_main.py` 新規作成

### Warning
- W-01: `MemoryManager.__init__` に docstring 追加
- W-02: `validate_scenario` の重複バリデーション削除
- W-03: `visualization.py` フォント検索失敗時の警告ログ追加
- W-04: モジュール docstring のセクション参照修正 (SS → §)
- W-05: `VetoCaps`/`CriticWeights`/`StateTransitionConfig` に Field(description) 追加
- W-06: `run_single_day` docstring に `prev_endings` 引数追加
- W-07: `CriticLog.save` の追記モード副作用を文書化
- W-08: `output_dir` にパストラバーサル検証追加
- W-09: tests/ の ruff エラー修正 (31件)

## 受け入れ条件
- [ ] ruff check csdg/ tests/ がエラー 0
- [ ] ruff format --check がクリーン
- [ ] mypy csdg/ --strict がPass
- [ ] pytest tests/ -v が全Pass
- [ ] 新規テスト test_main.py が追加されている

## 影響範囲
- csdg/engine/pipeline.py, actor.py, critic.py, memory.py, critic_log.py
- csdg/config.py, main.py, scenario.py, visualization.py
- tests/ 全ファイル + tests/test_main.py (新規)
