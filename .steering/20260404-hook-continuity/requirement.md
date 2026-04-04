# 要件定義: フック連続性強化 (v2.1)

## 背景
v2 で「フック強化 + Critic 診断軸 + 前日接続」を実装済み。
本修正はフックを「単発で作る」から「連続して繋ぐ」へ進化させる追加改善。

## 実装内容
1. Prompt_Generator.md: フック回収義務 + 再帰性 + 1つ限定
2. Prompt_Critic.md: prev_day_ending プレースホルダ追加 + フック未回収検知
3. critic.py: CriticPipeline/LLMJudge/Critic に prev_day_ending を伝搬
4. pipeline.py: evaluate_full() に prev_day_ending を渡す

## 受け入れ条件
- [ ] 既存テスト全 Pass
- [ ] 新規テスト Pass
- [ ] mypy --strict エラーなし
- [ ] ruff check/format エラーなし
- [ ] judge() が hook_strength を参照していないこと (v2 不変)
- [ ] L1/L2 のシグネチャ・ロジックに変更がないこと

## 影響範囲
- prompts/Prompt_Generator.md
- prompts/Prompt_Critic.md
- csdg/engine/critic.py
- csdg/engine/pipeline.py
- tests/test_critic.py
