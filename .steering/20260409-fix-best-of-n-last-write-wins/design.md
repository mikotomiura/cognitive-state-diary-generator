# 設計: Best-of-N last-write-wins バグ修正

## 実装アプローチ

### 根本原因
`run_single_day()` の success break path（line 1175）で `final_diary = diary_text` と無条件に
最後の attempt の diary を選んでいる。フォールバック（else:）パスには既に `_select_best_candidate()`
が実装済みだが、success path には適用されていない。

### 修正内容
success break 直前に以下の分岐を追加:

```python
if len(candidates) > 1:
    best = self._select_best_candidate(candidates)
    if best.attempt != candidate.attempt:
        logger.info("[Day %d] Best-of-N: candidate %d ... selected over latest %d ...", ...)
    final_diary = best.diary_text
    curr_state = best.state
else:
    final_diary = diary_text
```

- `len(candidates) > 1`: ボーナス再試行が発生した場合のみ有効（Day 1 等の単一ケースは unchanged）
- `curr_state = best.state`: diary と state の整合性を保つ（欠落すると actual_delta が不整合）
- `_select_best_candidate()` は既存実装: `max(candidates, key=lambda c: c.total_score - c.structural_violation_count)`

## 変更対象ファイル
| ファイル | 変更内容 |
|---|---|
| `csdg/engine/pipeline.py` | success path の final_diary 設定を Best-of-N に変更 |
| `tests/test_pipeline.py` | ボーナス再試行 Best-of-N を検証するテストを追加 |

## 代替案と選定理由
- `final_diary = diary_text` を直接 `_select_best_candidate(candidates).diary_text` に置き換える案 → 単一候補ケースでも余計な関数呼び出しが発生。`len(candidates) > 1` 条件で分岐する現行案が意図を明示的に伝える。
