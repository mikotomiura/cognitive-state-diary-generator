# 要件定義: Actor モジュール

## 背景
パイプラインの Phase 1 (状態遷移) と Phase 2 (日記生成) を担当する Actor クラスが未実装。
LLMClient を介して LLM を呼び出し、プロンプトファイルをテンプレート展開して使用する。

## 実装内容
- `Actor` クラス: `update_state()` (Phase 1) と `generate_diary()` (Phase 2)
- プロンプトファイルを外部から読み込み、プレースホルダをテンプレート展開する
- `tests/conftest.py` に共通フィクスチャを追加
- `tests/test_actor.py` にテストを作成

## 受け入れ条件
- [x] `update_state` と `generate_diary` が実装されている
- [x] プロンプトを `prompts/` から外部ファイルとして読み込んでいる
- [x] テストが全件 Pass
- [x] mypy --strict, ruff check がエラー 0

## 影響範囲
- `csdg/engine/actor.py` - 新規作成
- `tests/conftest.py` - 新規作成
- `tests/test_actor.py` - 新規作成
