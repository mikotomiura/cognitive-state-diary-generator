# タスクリスト: v3 未実装機能

## 実装タスク
- [x] schemas.py に LLMDeltaResponse を追加
- [x] config.py に VetoCaps / veto_cap 設定を追加
- [x] critic.py に has_critical_failure() と veto ロジックを実装
- [x] critic.py に禁止一人称検出を追加
- [x] critic.py の LLMJudge に逆推定一致チェックを追加
- [x] critic.py の CriticResult に inverse_estimation_score, veto_applied を追加
- [x] critic_log.py の CriticLogEntry に llm_delta_reason, inverse_estimation_score を追加
- [x] pipeline.py で inverse_estimation_score を CriticLogEntry に記録

## テストタスク
- [x] veto 発動時の最終スコアキャップ検証
- [x] veto 非発動時の通常重み付き平均検証
- [x] 逆推定一致スコアが低い場合の emotional 軸 veto 検証
- [x] LLMDeltaResponse.reason バリデーションテスト (空文字拒否)
- [x] has_critical_failure() の各条件テスト (禁止一人称/文字数逸脱/trigram overlap)
- [x] CriticLogEntry 新フィールドの保存・読み込み往復テスト
- [x] 禁止一人称検出テスト
- [x] 逆推定一致スコア記録テスト

## ドキュメント更新
- [x] docs/architecture.md — Veto権、逆推定一致チェック、LLMDeltaResponse を反映
- [x] docs/repository-structure.md — schemas.py の新型を追記

## 検証結果
- 277テスト全パス (259既存 + 18新規)
- ruff check csdg/ クリーン
- mypy strict: 既存3エラーのみ (pydantic-settings/matplotlib stubs)
