# 要件定義: advice.md v3 未実装機能の追加

## 背景
MVP最終検証でCriticScore emotional が全Day=4で固定される問題が確認済み。
advice.md v3 で追加された以下の機能が未実装のため、Criticの評価分解能が不十分。

## 実装内容
1. **LLM Delta Reason フィールド** — LLMDeltaResponse に reason を追加
2. **Veto権メカニズム** — RuleBasedValidator.has_critical_failure() + veto cap
3. **逆推定一致チェック** — 状態-文章の因果整合性評価
4. **CriticLogEntry 拡張** — llm_delta_reason, inverse_estimation_score フィールド

## 受け入れ条件
- [ ] LLMDeltaResponse が schemas.py に追加されている
- [ ] Veto権が致命的違反時に最終スコアをキャップする
- [ ] 逆推定一致スコアが CriticResult に記録される
- [ ] CriticLogEntry に新フィールドが追加されている
- [ ] 既存184テスト + 新規テストが全パス
- [ ] mypy strict / ruff クリーン

## 影響範囲
- csdg/schemas.py
- csdg/config.py
- csdg/engine/critic.py
- csdg/engine/critic_log.py
- csdg/engine/state_transition.py
- csdg/engine/pipeline.py
- tests/test_critic.py
- tests/test_critic_log.py
- tests/test_state_transition.py
