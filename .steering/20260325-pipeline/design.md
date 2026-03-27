# 設計: Pipeline モジュール実装

## 実装アプローチ
- architecture.md §3.4, §4 に準拠
- Phase 1: ValidationError を最大3回リトライ → 前日状態コピー fallback
- Phase 2+3: Actor-Critic ループ、Temperature Decay、Best-of-N
- メモリ: diary_text[:100] + "..." のスライディングウィンドウ (MVP)
- 連続3Day失敗でパイプライン中断

## 変更対象ファイル
| ファイル | 変更内容 |
|---|---|
| `csdg/engine/pipeline.py` | 新規: RetryCandidate + PipelineRunner |
| `tests/test_pipeline.py` | 新規: 8パターンのテスト |
