# タスクリスト: MVP後改善

## タスク2: 状態遷移の半数式化 ✅
- [x] schemas.py に EmotionalDelta 型を追加
- [x] config.py に StateTransitionConfig 設定を追加
- [x] engine/state_transition.py を新設 (compute_next_state, compute_event_impact)
- [x] engine/actor.py を delta 提案方式に変更 (LLM出力→delta抽出→数式統合)
- [x] engine/pipeline.py の後方互換性を維持
- [x] tests/test_state_transition.py を追加 (10テスト)
- [x] 既存テスト修正 (test_actor.py の半数式化対応)
- [x] mypy strict / ruff クリーン

## タスク3: 2層メモリ構造 ✅
- [x] schemas.py に TurningPoint / LongTermMemory / ShortTermMemory / Memory 型を追加
- [x] engine/memory.py を新設 (MemoryManager)
- [x] engine/pipeline.py のメモリ管理を MemoryManager に統合
- [x] tests/test_memory.py を追加 (17テスト)
- [x] 既存テスト全パス確認
- [x] mypy strict / ruff クリーン

## タスク1: Critic 3層分解 ✅
- [x] schemas.py に LayerScore / CriticResult 型を追加
- [x] config.py に CriticWeights 設定を追加
- [x] engine/critic.py に RuleBasedValidator を追加
- [x] engine/critic.py に StatisticalChecker を追加
- [x] engine/critic.py に LLMJudge を追加
- [x] engine/critic.py に CriticPipeline を追加
- [x] Critic クラスの後方互換性を維持 (内部で CriticPipeline を使用)
- [x] tests/test_critic.py を大幅拡張 (31テスト)
- [x] 既存テスト全パス確認
- [x] mypy strict / ruff クリーン

## ドキュメント更新 ✅
- [x] docs/architecture.md に新スキーマ・モジュールを反映
- [x] docs/repository-structure.md に新規ファイルを追記

## 最終確認
- [x] 全231テストパス
- [x] mypy strict: Success (13 source files)
- [x] ruff check: All checks passed
- [x] ruff format: All files formatted
