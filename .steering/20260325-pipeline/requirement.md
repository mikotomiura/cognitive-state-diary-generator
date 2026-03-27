# 要件定義: Pipeline モジュール実装

## 背景
3-Phase パイプラインの実行制御を担う心臓部が未実装。
Actor-Critic ループの制御、リトライ、フォールバック、メモリ管理を統合する。

## 実装内容
1. RetryCandidate データクラス
2. PipelineRunner クラス (run, run_single_day, memory_buffer, fallback, best-of-N)

## 受け入れ条件
- [ ] run と run_single_day が実装されている
- [ ] リトライ制御 (Temperature Decay + Best-of-N) が動作する
- [ ] Phase 1 フォールバックが動作する
- [ ] memory_buffer のスライディングウィンドウが動作する
- [ ] pytest tests/test_pipeline.py -v が全件 Pass
- [ ] mypy --strict エラー 0
- [ ] ruff check エラー 0

## 影響範囲
- `csdg/engine/pipeline.py` (新規)
- `tests/test_pipeline.py` (新規)
