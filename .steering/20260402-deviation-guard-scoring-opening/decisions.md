# 決定事項記録: Deviation Guard + Scoring 最適化 + Opening 検出精緻化

## 2026-04-02 改善 A/B/C の採用判定

### 変更前後のスコア比較

| 指標 | Run 2 (H/I後) | Run 3 (A/B/C後) | 変化 |
|---|---|---|---|
| フォールバック | 1 | 0 | 改善 |
| リトライ | 6 | 4 | 改善 |
| emotional_plausibility=4 | 1/7 | 4/7 | 大幅改善 |
| Opening 多様性 | 6/7 | 7/7 | 改善 |

### 各改善の効果判定

| 改善 | 効果 | 採用 |
|---|---|---|
| A: Deviation Guard | 今回は発動せず（max_dev < 0.10）。Day 1 型フォールバックの保険 | 採用 |
| B: Layer 1/2 閾値最適化 | emotional_plausibility=4 が 1/7→4/7 に改善 | 採用 |
| C: Opening 検出精緻化 | Opening 多様性 7/7 達成 | 採用 |

### 重要な決定
- Layer 1 のペナルティ閾値を 0.12→0.15 に緩和し、ペナルティ幅を -1.0→-0.5 に縮小した
- Layer 2 の neutral 帯を 0.25→0.30 に拡大した
- これにより emotional_plausibility のスコア分布が改善し、品質の識別力が向上した
