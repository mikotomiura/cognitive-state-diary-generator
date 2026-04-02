# 設計: Deviation Guard + Scoring 最適化 + Opening 検出精緻化

## 実装アプローチ

### A: Phase 1 Deviation Guard
pipeline.py の `run_single_day()` Phase 1 完了後に:
1. `compute_expected_delta()` と `compute_deviation()` で deviation を計算
2. max_dev > 0.10 なら各パラメータを expected 方向に α=0.5 でブレンド
3. ブレンド後の値で curr_state を更新（clamp 適用）
4. ログ出力で補正の適用を記録

### B: Layer 1/2 閾値最適化
critic.py の既存スコアリングコードの閾値数値を変更するのみ。

### C: Opening 検出
`_detect_opening_pattern()` の会話型チェック (L277) の直後、五感型チェック (L293) の前に正規表現パターンを追加。

## 変更対象ファイル
| ファイル | 変更内容 |
|---|---|
| `csdg/engine/pipeline.py` | Phase 1 deviation guard 追加、opening detection 精緻化 |
| `csdg/engine/critic.py` | Layer 1/2 emotional_plausibility 閾値変更 |
| `tests/test_pipeline.py` | deviation guard テスト、opening detection テスト追加 |
| `tests/test_critic.py` | Layer 1/2 閾値テスト更新 |

## 代替案と選定理由
- Phase 1 リトライ案 → 複雑度が高い。ソフト補正の方が確実かつシンプル。
- deviation 正規化案 → 低インパクトイベントのみ対処。ソフト補正は全ケースをカバー。
