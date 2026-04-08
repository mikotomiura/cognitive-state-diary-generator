# 要件定義: Best-of-N last-write-wins バグ修正

## バグの症状
構造的制約違反によるボーナス再試行が発生した場合（`structural_retry_used`フラグが立つケース）、
`run_single_day()` の success path で常に最後の attempt の日記が使われる（last-write-wins）。

## 期待される動作
複数の attempt が candidates リストに蓄積されている場合（ボーナス再試行が発生した場合）は、
`_select_best_candidate()` によりスコアが最大の候補を選択すべき。

## 再現手順
1. 1日目の attempt 0 が Critic Pass するが structural violations あり → ボーナス再試行
2. attempt 1 (ボーナス) も Critic Pass するが、total_score が attempt 0 より低い
3. 現状: attempt 1 の日記が返却される (last-write-wins)
4. 期待: attempt 0 の日記が返却される (Best-of-N)

## 影響範囲
- `csdg/engine/pipeline.py` の `PipelineRunner.run_single_day()` success path (line 1175)
- フォールバック（全リトライ消費）パスは既存の Best-of-N で正しく動作している

## 受け入れ条件
- [ ] ボーナス再試行後、`_select_best_candidate()` で最良候補が選ばれる
- [ ] 単一候補（ボーナスなし）ケースは変化なし
- [ ] `curr_state` もベスト候補のものに更新される（diary と state の整合性）
- [ ] 既存テストすべて Pass
