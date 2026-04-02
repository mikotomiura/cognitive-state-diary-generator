# 設計: HumanCondition（人間らしさ注入）

## 実装アプローチ
独立した HUM 層ではなく、既存の CharacterState にサブモデルとして統合する。状態遷移は決定論的計算で行い、LLM への依存を増やさない。

## 変更対象ファイル
| ファイル | 変更内容 |
|---|---|
| `csdg/schemas.py` | `HumanCondition` モデル新規追加、`CharacterState` に `human_condition` フィールド追加 |
| `csdg/engine/state_transition.py` | `compute_human_condition()` 関数追加、`compute_next_state()` でHC更新を統合 |
| `csdg/scenario.py` | `INITIAL_STATE` に `human_condition` 追加 |
| `prompts/Prompt_StateUpdate.md` | HumanCondition 更新の指示セクション追加 |
| `prompts/Prompt_Generator.md` | HumanCondition に応じた文体変化ルール追加 |
| `prompts/Prompt_Critic.md` | HumanCondition 整合性の評価基準追加 |
| `tests/test_schemas.py` | HumanCondition バリデーションテスト |
| `tests/test_state_transition.py` | HumanCondition 遷移テスト |
| `docs/glossary.md` | 用語追加 |
| `docs/architecture.md` | 設計記述追加 |

## 代替案と選定理由
| 代替案 | 却下理由 |
|---|---|
| 独立 HUM パイプラインフェーズ | APIコール増加、既存3-Phase構造への侵入が大きい |
| プロンプトのみの変更 | 定量的な制御ができず再現性が低い |
| CharacterState のトップレベルに直接フィールド追加 | 既存フィールドとの混在で可読性低下 |
