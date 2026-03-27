# タスクリスト: advice.md 残存改善項目

## 実装タスク
- [ ] config.py: max_llm_delta, temperature_final, temperature_decay_constant 追加
- [ ] state_transition.py: delta clipping 実装
- [ ] config.py: temperature_schedule を指数減衰に変更
- [ ] critic_log.py: CriticLogEntry, CriticLog 実装
- [ ] pipeline.py: CriticLog 統合

## テストタスク
- [ ] test_state_transition.py: max_llm_delta clipping テスト
- [ ] test_config.py: 指数温度減衰テスト
- [ ] test_critic_log.py: 保存/読み込み/パターン集計テスト

## ドキュメント更新
- [ ] docs/architecture.md: 状態遷移・CriticLog設計を反映
- [ ] docs/repository-structure.md: critic_log.py を追記
