# 要件定義: Critic モジュール実装

## 背景
Phase 3（Critic評価）を担当するモジュールが未実装。Actor-Critic型の敵対的検証ループを完成させるために必要。

## 実装内容
1. 定量検証の純粋関数3つ（compute_expected_delta, compute_deviation, judge）
2. Critic クラス（LLMClient を介した CriticScore 生成）

## 受け入れ条件
- [ ] 3つの純粋関数が LLM に依存せず実装されている
- [ ] Critic.evaluate が CriticScore を返す
- [ ] pytest tests/test_critic.py -v が全件 Pass
- [ ] mypy --strict エラー 0
- [ ] ruff check エラー 0

## 影響範囲
- `csdg/engine/critic.py` (新規)
- `tests/test_critic.py` (新規)
