# 要件定義: HumanCondition（人間らしさ注入）

## 背景
advice.md の提案に基づく。現在の CharacterState はイベント駆動の感情パラメータ (fatigue, motivation, stress) のみで構成されており、人間特有の生物的・心理的要因（睡眠の質、気分の慣性、認知負荷、感情的葛藤）がモデル化されていない。これにより日記が「イベントへの反応」に偏り、「人間としての存在感」が不足している。

## 実装内容
1. `HumanCondition` サブモデルを `CharacterState` に追加
2. 状態遷移ロジックに HumanCondition の自動更新を実装
3. 3本のプロンプト (StateUpdate / Generator / Critic) を HumanCondition 対応に拡張
4. シナリオ初期状態に HumanCondition のデフォルト値を追加

## 受け入れ条件
- [ ] `HumanCondition` モデルが schemas.py に定義されている
- [ ] `CharacterState` に `human_condition` フィールドが追加されている
- [ ] 状態遷移で HumanCondition が自動更新される
- [ ] Generator プロンプトが HumanCondition に応じた文体指示を含む
- [ ] Critic プロンプトが HumanCondition との整合性を評価する
- [ ] 全テスト Pass / mypy --strict Pass / ruff check Pass
- [ ] glossary.md, architecture.md が更新されている

## 影響範囲
- `csdg/schemas.py` — HumanCondition モデル追加、CharacterState 拡張
- `csdg/engine/state_transition.py` — HumanCondition 遷移ロジック
- `csdg/scenario.py` — 初期状態更新
- `prompts/Prompt_StateUpdate.md` — 更新ルール追加
- `prompts/Prompt_Generator.md` — 文体指示追加
- `prompts/Prompt_Critic.md` — 評価基準追加
- `tests/test_schemas.py` — バリデーションテスト
- `tests/test_state_transition.py` — 遷移テスト
- `docs/glossary.md` — 用語追加
- `docs/architecture.md` — 設計記述追加
