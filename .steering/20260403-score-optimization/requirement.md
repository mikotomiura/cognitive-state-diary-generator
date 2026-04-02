# 要件定義: スコア最適化 (A+B+C+D+E)

## 背景
5 Run の分析で3つのボトルネックを特定:
1. L1/L2 emotional_plausibility の加点閾値が Deviation Guard 後の実測値に対して厳しすぎる
2. 文字数構造違反でリトライが品質改善でなく形式修正に消費される
3. Day 1 の HumanCondition がデフォルトで特徴がない

## 実装内容
- A: L1 emotional_plausibility 加点閾値緩和
- B: L2 emotional_plausibility 加点閾値緩和
- C: 構造違反の文字数理想範囲を 420→450 に拡大
- D: Day 1 の初期 HumanCondition を非デフォルトに
- E: 書き出し/余韻の推奨パターン指定強化

## 受け入れ条件
- [ ] 全テスト Pass / mypy --strict / ruff check
- [ ] パイプライン実行で 7/7 完走
- [ ] emotional_plausibility=4 の出現率が向上

## 影響範囲
- `csdg/engine/critic.py` (A, B)
- `csdg/engine/pipeline.py` (C)
- `csdg/scenario.py` (D)
- `csdg/engine/actor.py` (E)
