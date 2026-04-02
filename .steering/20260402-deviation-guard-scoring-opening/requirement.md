# 要件定義: Deviation Guard + Scoring 最適化 + Opening 検出精緻化

## 背景
v4 パイプライン再実行の結果、以下の3つの根本的問題を特定:
1. Day 1 で Phase 1 の motivation deviation=0.127 が原因で 3回とも emotional_plausibility=2 → フォールバック発生。Phase 2/3 リトライでは deviation は不変のため構造的に回復不能。
2. emotional_plausibility が全Day で 3 固定（Day 7 のみ 4）。Layer 1 の max_dev >= 0.12 → -1.0 ペナルティが急峻すぎる。
3. Opening 多様性 6/7。「声」が五感キーワードに含まれるため「人名+声が」パターンが五感型に誤分類。

## 実装内容

### A: Phase 1 Deviation Guard
Phase 1 完了後に deviation を即座に計算。max_dev > 0.10 の場合、actual values を expected_delta 方向に α=0.5 でソフトブレンド補正。

### B: Layer 1/2 emotional_plausibility 閾値最適化
- Layer 1: 0.08-0.10 に +0.25 加点帯追加。ペナルティ閾値を 0.12→0.15 に緩和、幅を -1.0→-0.5 に縮小。
- Layer 2: +0.5 加点帯を 0.10→0.15 に拡大、neutral 帯を 0.25→0.30 に拡大。

### C: 開幕パターン検出精緻化
`_detect_opening_pattern()` で五感キーワードチェックの前に「人名+声/言葉/一言」パターンを会話型として検出。

## 受け入れ条件
- [ ] Phase 1 後に deviation guard が動作し、max_dev > 0.10 で補正が適用される
- [ ] Layer 1/2 の閾値が最適化されている
- [ ] 「人名+声が」パターンが「会話型」として検出される
- [ ] 既存テスト全件 Pass + 新規テスト追加
- [ ] mypy --strict エラーなし
- [ ] パイプライン再実行で fallback 0, emotional_plausibility 改善

## 影響範囲
- `csdg/engine/pipeline.py` — deviation guard, opening detection
- `csdg/engine/critic.py` — Layer 1/2 scoring thresholds
- `csdg/config.py` — deviation guard 定数（必要な場合）
