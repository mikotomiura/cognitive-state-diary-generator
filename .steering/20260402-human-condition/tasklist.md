# タスクリスト: HumanCondition（人間らしさ注入）

## 実装タスク
- [x] Phase 1: schemas.py に HumanCondition モデル追加
- [x] Phase 1: CharacterState に human_condition フィールド追加
- [x] Phase 2: state_transition.py に compute_human_condition() 追加
- [x] Phase 2: compute_next_state() で HC 更新を統合
- [x] Phase 3: Prompt_StateUpdate.md に HC 更新ルール追加
- [x] Phase 3: Prompt_Generator.md に HC 文体指示追加
- [x] Phase 3: Prompt_Critic.md に HC 評価基準追加
- [x] Phase 4: scenario.py の INITIAL_STATE 更新

## テストタスク
- [x] test_schemas.py: HumanCondition バリデーション
- [x] test_state_transition.py: HC 遷移ロジック

## ドキュメント更新
- [x] glossary.md: HumanCondition 関連用語
- [ ] architecture.md: HC の位置づけ（軽微なため省略可）

## 検証結果
- 505 tests passed
- mypy --strict: Success (0 errors)
- ruff check: All checks passed
