# 設計: advice.md 残存改善項目

## 実装アプローチ

### 1. max_llm_delta clipping
- `StateTransitionConfig` に `max_llm_delta: float = 0.3` 追加
- `compute_next_state()` で `delta_val = clamp(delta_val, -max_llm_delta, +max_llm_delta)` を追加
- clipはllm_weight乗算の前に行う

### 2. 指数温度減衰
- `CSDGConfig` に `temperature_final: float = 0.3`, `temperature_decay_constant: float | None = None` 追加
- `temperature_schedule` プロパティを指数減衰に変更:
  `temp = final + (initial - final) * exp(-decay_constant * i)`
- decay_constant デフォルト: max_retries / 3

### 3. Critic Log
- `csdg/engine/critic_log.py` を新設
- スキーマは schemas.py に追加せず、critic_log.py 内で Pydantic モデルとして定義
- JSON Lines 形式 (.jsonl) で永続化
- `CriticLog.get_low_score_patterns()` で failure_patterns を頻度順集計

### 4. Actor プロンプト注入
- pipeline.py で CriticLog を保持、Day実行前に低スコアパターンを取得
- Actor.generate_diary() の revision_instruction 引数経由で注入

## 変更対象ファイル
| ファイル | 変更内容 |
|---|---|
| `csdg/config.py` | max_llm_delta, temperature関連パラメータ追加 |
| `csdg/engine/state_transition.py` | delta clipping 追加 |
| `csdg/engine/critic_log.py` | 新設 |
| `csdg/engine/pipeline.py` | CriticLog統合 |
| `tests/test_state_transition.py` | clipping テスト追加 |
| `tests/test_config.py` | 指数減衰テスト追加 |
| `tests/test_critic_log.py` | 新設 |
| `docs/architecture.md` | 設計反映 |
| `docs/repository-structure.md` | 新規ファイル追記 |

## 代替案と選定理由
- CriticLogEntry を schemas.py に置く案 → critic_log.py は独立モジュールなので、内部に閉じる方がモジュール凝集度が高い
- Actor プロンプト注入を専用プロンプトファイルにする案 → 動的生成のため外部ファイル化は不適切
