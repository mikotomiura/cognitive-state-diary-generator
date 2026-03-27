# 要件定義: MVP後改善 (Critic 3層分解 / 状態遷移半数式化 / 2層メモリ)

## 背景
MVP最終検証で CriticScore の emotional が全Day=4で固定されていることが判明。
Criticの評価分解能、状態遷移の再現性、長期記憶の欠如を改善する。

## 実装内容
1. **タスク2:** `engine/state_transition.py` — 決定論的骨格 + LLM delta 補正
2. **タスク3:** `engine/memory.py` — ShortTermMemory + LongTermMemory 2層構造
3. **タスク1:** `engine/critic.py` — 3層分解 (RuleBased + Statistical + LLMJudge)

## 受け入れ条件
- [ ] 既存184テスト全パス
- [ ] mypy strict / ruff クリーン
- [ ] 新規テストでカバレッジ95%以上
- [ ] schemas.py 変更を architecture.md に反映
- [ ] repository-structure.md に新規ファイルを追記
- [ ] 各タスクを個別コミット (conventional commits形式)

## 影響範囲
- `csdg/engine/` — state_transition.py (新規), memory.py (新規), critic.py (大幅変更)
- `csdg/config.py` — 新設定項目追加
- `csdg/schemas.py` — 新型追加
- `csdg/engine/pipeline.py` — 統合ポイント変更
- `csdg/engine/actor.py` — delta提案方式への変更
- `prompts/` — プロンプト修正
- `tests/` — 新規テスト追加
