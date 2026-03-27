# タスクリスト: Pipeline モジュール実装

## 実装タスク
- [ ] RetryCandidate dataclass
- [ ] PipelineRunner.__init__
- [ ] PipelineRunner.run (全Day制御, 連続失敗チェック)
- [ ] PipelineRunner.run_single_day (Phase1→Phase2+3ループ)
- [ ] _update_memory_buffer
- [ ] _create_fallback_state
- [ ] _select_best_candidate

## テストタスク
- [ ] 正常系: 全7Day が1回で Pass
- [ ] リトライ: Phase 3 で Reject → リトライで Pass
- [ ] Temperature Decay
- [ ] Best-of-N
- [ ] Phase 1 フォールバック
- [ ] memory_buffer スライディングウィンドウ
- [ ] Dayスキップ
- [ ] パイプライン中断

## 検証タスク
- [ ] pytest 全件 Pass
- [ ] mypy --strict エラー 0
- [ ] ruff check / ruff format エラー 0
