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

## 追加修正タスク (残課題修正)
- [x] prev_diary を pipeline → critic に受け渡し
- [x] LLMDeltaResponse を actor.py に統合 (ヒューリスティック reason 生成)
- [x] llm_delta_reason を CriticLogEntry に記録
- [x] prompt_hashes の実装
- [x] architecture.md / repository-structure.md を Anthropic 実装に同期
- [x] Memory LLM 抽出の実装 (Prompt_MemoryExtract.md + MemoryExtraction スキーマ)
- [x] 実パイプライン実行 + スコア分布検証

## 検証結果 (最終)
- 289テスト全パス (259既存 + 30新規)
- ruff check csdg/ クリーン
- mypy strict: no issues found in 14 source files
- 実パイプライン: 7/7 Day 完了, リトライ1回, フォールバック0回
- emotional_plausibility: ユニーク値2 (4, 5) — v3改善が機能
- Day 6 で Veto (persona_deviation) 発動 → リトライで修正確認

## 最終検証・チューニングタスク
- [x] Prompt_MemoryExtract.md の存在確認・作成 (既存確認済み、プレースホルダ一致)
- [x] repository-structure.md §2.2 / §5.2 / §4.2 の修正
- [x] Prompt_Critic.md チューニング (deviation 定量基準 + 採点注意事項)
- [x] チューニング後のパイプライン再実行
- [x] 前回結果との比較分析
- [x] (条件付き) 追加チューニング — 不要と判断 (全deviation<0.1のため構造的限界)

## 検証結果 (チューニング後)
- 289テスト全パス、ruff check クリーン
- 実パイプライン: 7/7 Day 完了, リトライ1回, フォールバック0回
- emotional_plausibility: [4,4,4,4,4,4,5] 平均 4.43→4.14 (厳格化成功)
- Day 4 (crisis, impact=-0.9): emotional 5→4 (適切に厳格化)
- Day 7 (deviation=0.029): emotional 5 (定量基準に適合)
- 全Dayのmax_deviation < 0.1 — Actorの状態遷移精度が高い
