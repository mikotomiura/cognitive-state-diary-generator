# 要件定義: フック強化 + Critic診断軸追加

## 背景
CSDGパイプライン v4+ は 7/7 Critic Pass で安定稼働中。
出力テキスト精査の結果、3つの品質課題が特定された:
- 課題A: 「余韻」と「フック」の混同（Day末尾がフックとして機能していない）
- 課題B: 日を跨ぐ連続性がテーマレベルに留まっている
- 課題C: Criticが「続きを読みたいか」を測定していない

## 実装内容
1. Prompt_Generator.md にフック定義・前日接続指示・セルフチェックを追加
2. Prompt_Critic.md に hook_strength 診断軸を追加（Pass/Fail非影響）
3. CriticScore に hook_strength フィールド追加
4. actor.py に prev_day_ending パラメータ追加
5. pipeline.py で prev_day_ending の収集・注入
6. critic.py で hook_strength を L3 → 最終スコアに転送

## 受け入れ条件
- [ ] 既存テスト全 Pass
- [ ] hook_strength の新規テスト Pass
- [ ] mypy --strict エラーなし
- [ ] ruff check/format エラーなし
- [ ] judge() が hook_strength を参照していないこと
- [ ] prev_day_ending 空文字列時に前日接続セクション非注入

## 影響範囲
- prompts/Prompt_Generator.md
- prompts/Prompt_Critic.md
- csdg/schemas.py
- csdg/engine/actor.py
- csdg/engine/pipeline.py
- csdg/engine/critic.py
- tests/test_schemas.py
- tests/test_critic.py
- tests/test_actor.py
