# 機能設計書 (Functional Design Document)

> **目的:** CSDG（Cognitive-State Diary Generator）が「何をするシステムか」「何ができるか」「どのような入力を受け取り、どのような出力を返すか」を定義する。
> 技術的な実装方法は `architecture.md` に、ファイル配置は `repository-structure.md` に委譲する。
> 本ドキュメントはシステムの「振る舞い」を記述する。

---

## 1. システムの目的と範囲

### 1.1 システムの目的

CSDGは、以下の問いに対する技術的回答として設計されたシステムである:

**「LLMは、1週間という時間軸の中で、キャラクターの感情変化と人格の一貫性を両立させた連続テキストを生成できるか？」**

具体的には、架空のキャラクター「三浦とこみ」が7日間にわたって書くブログ日記を、以下の品質基準を満たした形で自動生成する:
- 日記間の時間的整合性が保たれている（過去の出来事との矛盾がない）
- イベントに対する感情変化が自然で妥当である
- キャラクターの性格・口調・禁則事項が全日記を通じて維持されている

### 1.2 システムの範囲

**スコープ内:**
- 7日分のブログ日記テキスト（Markdown形式）の自動生成
- キャラクターの感情状態の構造化管理と遷移
- 生成された日記の定量的品質評価（Actor-Critic）
- 品質基準未達時の自動リトライとフォールバック
- 実行ログの永続化と感情パラメータの可視化

**スコープ外:**
- Web UIの提供（将来拡張として `architecture.md` に記載）
- 複数キャラクターの同時生成
- ユーザーとの対話的なシナリオ変更
- 日記の多言語対応
- 生成された日記のソーシャルメディアへの自動投稿

---

## 2. ユースケース

### UC-01: パイプラインの完全実行

| 項目 | 内容 |
|---|---|
| **アクター** | 開発者 / 実行者 |
| **目的** | 7日間分の日記を一括生成する |
| **事前条件** | API キーが環境変数に設定されている、プロンプトファイルが配置されている |
| **トリガー** | `python -m csdg.main` の実行 |
| **基本フロー** | 1. システムは `scenario.py` から7日分の `DailyEvent` と初期状態 `h_0` を読み込む |
| | 2. Day 1 から Day 7 まで順次、3フェーズパイプラインを実行する |
| | 3. 各Dayの処理完了時に、日記ファイル `output/day_XX.md` を出力する |
| | 4. 全Day完了後、`output/generation_log.json` と `output/state_trajectory.png` を出力する |
| **事後条件** | `output/` ディレクトリに7つの日記ファイル、ログ、グラフが生成されている |
| **代替フロー** | Phase 1でバリデーションエラーが発生した場合 → Self-Healingフォールバック |
| | Phase 3で全リトライが Reject の場合 → Best-of-N フォールバック |
| | 連続3Day以上失敗の場合 → パイプライン中断、生成済み成果物を保存 |

### UC-02: 特定Dayのみの実行

| 項目 | 内容 |
|---|---|
| **アクター** | 開発者 |
| **目的** | デバッグや調整のため、特定の1日分のみ再生成する |
| **事前条件** | UC-01の事前条件に加え、該当Dayの前日までの状態が利用可能であること |
| **トリガー** | `python -m csdg.main --day 4` の実行 |
| **基本フロー** | 1. 指定されたDayの前日の状態を `generation_log.json` から復元する（存在しない場合は `h_0` を使用） |
| | 2. 指定されたDayのみ3フェーズパイプラインを実行する |
| | 3. 結果を `output/day_XX.md` に出力する（上書き） |
| **事後条件** | 指定Dayの日記ファイルが更新されている |
| **例外フロー** | 前日の状態ログが存在しない場合 → 初期状態 `h_0` から開始する |

### UC-03: 実行結果の分析

| 項目 | 内容 |
|---|---|
| **アクター** | 開発者 / 評価者 |
| **目的** | 生成された日記の品質とパイプラインの動作を分析する |
| **事前条件** | UC-01が完了し、`output/` ディレクトリに成果物が存在する |
| **トリガー** | `output/generation_log.json` および `output/state_trajectory.png` の確認 |
| **確認項目** | 1. 各Dayの CriticScore が合格ラインを超えているか |
| | 2. リトライ・フォールバックの発生頻度は許容範囲か |
| | 3. 感情パラメータの推移がシナリオ設計の想定と一致しているか |
| | 4. 各Phaseの処理時間にボトルネックがないか |

### UC-04: シナリオの変更

| 項目 | 内容 |
|---|---|
| **アクター** | 開発者 |
| **目的** | 7日間のイベントを変更して異なる物語を生成する |
| **事前条件** | `scenario.py` の構造を理解していること |
| **手順** | 1. `scenario.py` の `DailyEvent` リストを編集する |
| | 2. `emotional_impact` が -1.0〜+1.0 の範囲内であることを確認する |
| | 3. `event_type` が `positive` / `negative` / `neutral` のいずれかであることを確認する |
| | 4. 必要に応じて初期状態 `h_0` を調整する |
| | 5. UC-01を実行して結果を確認する |
| **制約** | `day` フィールドは1から連番であること。Day数の上限は制約しないが、7日を推奨 |

### UC-05: プロンプトのチューニング

| 項目 | 内容 |
|---|---|
| **アクター** | 開発者 |
| **目的** | 生成品質の向上のためプロンプトを調整する |
| **手順** | 1. `output/generation_log.json` から低スコアのDayを特定する |
| | 2. 該当Dayの CriticScore の `reject_reason` を確認する |
| | 3. 対応する `prompts/` のMarkdownファイルを編集する |
| | 4. UC-02で該当Dayのみ再生成し、スコアの改善を確認する |
| **注意事項** | プロンプト変更時は `docs/glossary.md` のユビキタス言語と表現の一致を確認すること |

---

## 3. 機能要件

### F-01: 状態遷移 (Phase 1)

| ID | 要件 |
|---|---|
| F-01-01 | システムは、前日の `CharacterState` と当日の `DailyEvent` を入力として、新しい `CharacterState` を生成できること |
| F-01-02 | 出力される `CharacterState` は Pydantic バリデーションを通過すること |
| F-01-03 | 連続変数はクランプされること（`fatigue`: 0.0〜1.0、`motivation`, `stress`: -1.0〜1.0） |
| F-01-04 | `memory_buffer` は最大3件を超えないこと。超過した場合は古い要素から削除されること |
| F-01-05 | `relationships` に定義外の人物が追加されないこと |
| F-01-06 | バリデーションエラー発生時、最大3回リトライすること |
| F-01-07 | 3回リトライしても失敗した場合、前日の状態をコピーして暫定サマリを `memory_buffer` に挿入するフォールバックが実行されること |

### F-02: コンテンツ生成 (Phase 2)

| ID | 要件 |
|---|---|
| F-02-01 | システムは、更新された `CharacterState` と `DailyEvent` を入力として、ブログ日記テキスト（Markdown形式）を生成できること |
| F-02-02 | 生成される日記テキストは空文字列でないこと |
| F-02-03 | 生成される日記テキストはプレーンテキストまたはMarkdown形式であること（JSON形式でないこと） |
| F-02-04 | リトライ時には Critic の `revision_instruction` がプロンプトに注入されること |

### F-03: 品質評価 (Phase 3)

| ID | 要件 |
|---|---|
| F-03-01 | システムは、生成された日記と状態を入力として、`CriticScore` を出力できること |
| F-03-02 | `CriticScore` の各スコア（`temporal_consistency`, `emotional_plausibility`, `persona_deviation`）は1〜5の整数であること |
| F-03-03 | 全スコアが3以上の場合、Pass と判定されること |
| F-03-04 | 1つでも3未満のスコアがある場合、Reject と判定されること |
| F-03-05 | Reject時には `reject_reason` と `revision_instruction` が出力されること |
| F-03-06 | Criticのプロンプトに `expected_delta`（期待変動幅）と `deviation`（乖離）が注入されること |

### F-04: リトライ制御

| ID | 要件 |
|---|---|
| F-04-01 | Phase 3で Reject と判定された場合、Phase 2 から再実行されること |
| F-04-02 | リトライ時の Temperature は 0.7 → 0.5 → 0.3 と段階的に減衰すること |
| F-04-03 | 最大リトライ回数は3回（初回 + 2回リトライ）であること |
| F-04-04 | 最大リトライ回数を超えた場合、全候補の中から CriticScore 合計値が最大のものを採用すること（Best-of-N） |

### F-05: メモリ管理

| ID | 要件 |
|---|---|
| F-05-01 | 各Dayの処理完了時に、そのDayの日記の要約が `memory_buffer` に追加されること |
| F-05-02 | `memory_buffer` が3件を超えた場合、最も古い要素が削除されること（FIFO） |
| F-05-03 | `memory_buffer` の内容は Phase 1 と Phase 2 のプロンプトに注入されること |
| F-05-04 | Day 1 の処理時には `memory_buffer` は空であること |

### F-06: 出力

| ID | 要件 |
|---|---|
| F-06-01 | 各Dayの日記は `output/day_XX.md`（XX は2桁ゼロ埋め）として個別に出力されること |
| F-06-02 | 日記ファイルにはYAMLフロントマターとしてメタデータ（day, event_type, 感情パラメータ等）が含まれること |
| F-06-03 | パイプラインの実行ログは `output/generation_log.json` として出力されること |
| F-06-04 | 感情パラメータの推移グラフは `output/state_trajectory.png` として出力されること |
| F-06-05 | 出力ディレクトリが存在しない場合、自動的に作成されること |
| F-06-06 | 既存の出力ファイルが存在する場合、上書きされること |

### F-07: ペルソナ一貫性

| ID | 要件 |
|---|---|
| F-07-01 | 生成される全日記を通じて、キャラクターの一人称は「わたし」であること |
| F-07-02 | 生成される全日記に絵文字が含まれないこと |
| F-07-03 | 生成される日記に断定的な結論が含まれないこと（「......なのかもしれない」「分からないけど」等で終わること） |
| F-07-04 | 他人を見下す発言が含まれないこと |
| F-07-05 | 上記のペルソナ違反は CriticScore の `persona_deviation` で検出されること |

### F-08: エラーハンドリング

| ID | 要件 |
|---|---|
| F-08-01 | API接続エラー発生時、指数バックオフ（2^n秒、最大60秒）でリトライすること |
| F-08-02 | 予期しない例外が発生した場合、該当Dayをスキップし、エラー情報をログに記録すること |
| F-08-03 | 連続3Day以上のスキップが発生した場合、パイプラインを中断すること |
| F-08-04 | パイプライン中断時、生成済みの成果物は保存されること |
| F-08-05 | いかなるエラーが発生してもスタックトレースが `generation_log.json` に記録されること |

---

## 4. CLIインターフェース仕様

### 4.1 基本コマンド

```
python -m csdg.main [OPTIONS]
```

### 4.2 オプション一覧

| オプション | 型 | デフォルト | 説明 |
|---|---|---|---|
| `--day` | `int` | (なし) | 特定のDayのみ実行する。指定しない場合は全Day実行 |
| `--output-dir` | `str` | `output` | 出力ディレクトリのパス |
| `--skip-visualization` | `flag` | `False` | `state_trajectory.png` の生成をスキップする |
| `--verbose` | `flag` | `False` | 詳細なログを標準出力に表示する |
| `--dry-run` | `flag` | `False` | API呼び出しを行わず、パイプラインの構成確認のみ行う |

### 4.3 終了コード

| コード | 意味 |
|---|---|
| `0` | 正常終了（全Dayの生成が完了） |
| `1` | 部分的成功（一部のDayがスキップされたが、成果物は出力された） |
| `2` | パイプライン中断（連続3Day以上の失敗） |
| `3` | 設定エラー（APIキー未設定、プロンプトファイル欠落等） |

### 4.4 標準出力フォーマット

通常モード:
```
[CSDG] Starting pipeline (Day 1-7)
[Day 1] Phase 1: State Update ... OK (1.2s)
[Day 1] Phase 2: Content Generation ... OK (3.4s)
[Day 1] Phase 3: Critic Evaluation ... Pass (score: 4/4/5) (1.1s)
[Day 1] Saved: output/day_01.md
...
[Day 4] Phase 3: Critic Evaluation ... Reject (score: 2/3/4) → Retry 1/3
[Day 4] Phase 2: Content Generation (retry, temp=0.5) ... OK (3.8s)
[Day 4] Phase 3: Critic Evaluation ... Pass (score: 3/4/4) (1.0s)
[Day 4] Saved: output/day_04.md
...
[CSDG] Pipeline complete (7/7 days, 2 retries, 0 fallbacks)
[CSDG] Saved: output/generation_log.json
[CSDG] Saved: output/state_trajectory.png
```

Verbose モード（`--verbose`）:
```
[CSDG] Config: model=claude-sonnet-4-20250514, max_retries=3, initial_temp=0.7
[CSDG] Loaded 7 events from scenario.py
[CSDG] Initial state h_0: fatigue=0.1, motivation=0.2, stress=-0.1
[Day 1] Event: neutral/仕事 (impact=-0.15)
[Day 1] Phase 1: Prompt tokens=1,234 / Completion tokens=256
[Day 1] Phase 1: h_1 = {fatigue: 0.06, motivation: 0.28, stress: -0.05}
[Day 1] Phase 2: Prompt tokens=1,567 / Completion tokens=1,023
[Day 1] Phase 2: Generated 1,023 characters
[Day 1] Phase 3: expected_delta = {stress: -0.06, motivation: 0.08, fatigue: -0.04}
[Day 1] Phase 3: deviation = {stress: 0.01, motivation: 0.00, fatigue: 0.00}
[Day 1] Phase 3: Score = temporal:4 / emotional:4 / persona:5 → Pass
...
```

---

## 5. 入力仕様

### 5.1 シナリオ定義 (`scenario.py`)

7日分の `DailyEvent` を Python リスト として定義する。

**バリデーションルール:**
| ルール | 検証内容 |
|---|---|
| `day` の連続性 | 1 から始まり、連番であること（欠番なし） |
| `event_type` の値 | `positive`, `negative`, `neutral` のいずれかであること |
| `domain` の値 | 空文字列でないこと |
| `description` の値 | 空文字列でないこと、10文字以上であること |
| `emotional_impact` の範囲 | -1.0〜+1.0 であること |
| 物語アークとの整合性 | (手動確認) イベントの流れが物語構造と一致していること |

### 5.2 初期状態 (`h_0`)

`CharacterState` のインスタンスとして `scenario.py` に定義する。

**デフォルト初期状態:**
```python
initial_state = CharacterState(
    fatigue=0.1,
    motivation=0.2,
    stress=-0.1,
    current_focus="自動化スクリプトの本番投入が完了した直後の微妙な手持ち無沙汰",
    unresolved_issue=None,
    growth_theme="「考えること」と「生きること」の折り合い",
    memory_buffer=[],
    relationships={"深森那由他": 0.6, "ミナ": 0.4},
)
```

**制約:**
- 連続変数は -1.0〜1.0 の範囲内
- `memory_buffer` は空リスト（Day 1に記憶はない）
- `relationships` のキーはペルソナ定義の人物名と一致すること

### 5.3 プロンプトファイル

| ファイル | 必須 | 用途 |
|---|---|---|
| `prompts/System_Persona.md` | 必須 | キャラクターの不変ルール。全Phaseで使用 |
| `prompts/Prompt_StateUpdate.md` | 必須 | Phase 1: 状態遷移ルール |
| `prompts/Prompt_Generator.md` | 必須 | Phase 2: 日記生成ルール |
| `prompts/Prompt_Critic.md` | 必須 | Phase 3: 評価基準 |
| `prompts/Prompt_MemoryExtract.md` | 必須 | 長期記憶の信念・テーマ抽出 |
| `prompts/System_MemoryManager.md` | 必須 | メモリ管理システムプロンプト |

**起動時チェック:** パイプライン開始前に全プロンプトファイルの存在を確認し、欠落があれば終了コード3で終了する。

### 5.4 環境変数

| 変数名 | 必須 | デフォルト | 説明 |
|---|---|---|---|
| `CSDG_LLM_PROVIDER` | 任意 | `anthropic` | LLM プロバイダー (`anthropic` or `gemini`) |
| `CSDG_ANTHROPIC_API_KEY` | 条件付き必須 | — | Anthropic API キー (provider=anthropic 時に必須) |
| `CSDG_ANTHROPIC_MODEL` | 任意 | `claude-sonnet-4-20250514` | Claude モデル名 |
| `CSDG_GEMINI_API_KEY` | 条件付き必須 | — | Gemini API キー (provider=gemini 時に必須) |
| `CSDG_GEMINI_MODEL` | 任意 | `gemini-2.0-flash` | Gemini モデル名 |
| `CSDG_MAX_RETRIES` | 任意 | `3` | 最大リトライ回数 |
| `CSDG_INITIAL_TEMPERATURE` | 任意 | `0.7` | 初回生成時のTemperature |
| `CSDG_OUTPUT_DIR` | 任意 | `output` | 出力ディレクトリ |

---

## 6. 出力仕様

### 6.1 日記ファイル (`output/day_XX.md`)

**ファイル名規則:** `day_01.md`, `day_02.md`, ..., `day_07.md`（2桁ゼロ埋め）

**フォーマット:**
```markdown
---
day: 1
generated_at: "2025-01-15T14:30:00+09:00"
event_type: "neutral"
domain: "仕事"
emotional_impact: 0.2
state:
  fatigue: 0.06
  motivation: 0.28
  stress: -0.05
  current_focus: "自動化スクリプト完成後の手持ち無沙汰"
  growth_theme: "「考えること」と「生きること」の折り合い"
critic_score:
  temporal_consistency: 4
  emotional_plausibility: 4
  persona_deviation: 5
retry_count: 0
fallback_used: false
---

（ブログ日記本文 — Markdownテキスト）
```

**日記本文の制約:**
- 絵文字を含まないこと
- 一人称は「わたし」であること
- 物語アークの該当フェーズに適した感情トーンであること

### 6.2 実行ログ (`output/generation_log.json`)

**トップレベル構造:**
```json
{
  "pipeline_version": "1.0.0",
  "executed_at": "2025-01-15T14:30:00+09:00",
  "config": {
    "model": "claude-sonnet-4-20250514",
    "max_retries": 3,
    "initial_temperature": 0.7,
    "emotion_sensitivity": {
      "stress": -0.3,
      "motivation": 0.4,
      "fatigue": -0.2
    }
  },
  "prompt_hashes": {
    "System_Persona.md": "sha256:abcdef...",
    "Prompt_StateUpdate.md": "sha256:123456...",
    "Prompt_Generator.md": "sha256:789abc...",
    "Prompt_Critic.md": "sha256:def012..."
  },
  "records": [
    {
      "day": 1,
      "event": { "...DailyEvent..." },
      "initial_state": { "...CharacterState (h_{t-1})..." },
      "final_state": { "...CharacterState (h_t)..." },
      "diary_text": "（日記テキスト全文）",
      "critic_scores": [
        {
          "attempt": 1,
          "temperature": 0.7,
          "temporal_consistency": 4,
          "emotional_plausibility": 4,
          "persona_deviation": 5,
          "reject_reason": null,
          "revision_instruction": null
        }
      ],
      "retry_count": 0,
      "fallback_used": false,
      "phase1_duration_ms": 1200,
      "phase2_duration_ms": 3400,
      "phase3_duration_ms": 1100,
      "expected_delta": { "stress": -0.06, "motivation": 0.08, "fatigue": -0.04 },
      "actual_delta": { "stress": -0.05, "motivation": 0.08, "fatigue": -0.04 },
      "deviation": { "stress": 0.01, "motivation": 0.00, "fatigue": 0.00 }
    }
  ],
  "summary": {
    "total_days_processed": 7,
    "total_days_succeeded": 7,
    "total_days_skipped": 0,
    "total_retries": 2,
    "total_fallbacks": 0,
    "total_api_calls": 23,
    "total_duration_ms": 42000,
    "average_critic_score": {
      "temporal_consistency": 4.1,
      "emotional_plausibility": 3.9,
      "persona_deviation": 4.4
    }
  }
}
```

### 6.3 状態推移グラフ (`output/state_trajectory.png`)

**グラフ仕様:**

| 項目 | 仕様 |
|---|---|
| 画像サイズ | 1200 × 800 px |
| 構成 | 2段構成（上段: 感情パラメータ、下段: CriticScore） |
| 上段 X軸 | Day (1〜7) |
| 上段 Y軸 | パラメータ値 (-1.0〜1.0) |
| 上段 折れ線 | `stress`（赤, 実線）, `motivation`（青, 実線）, `fatigue`（灰, 破線） |
| 上段 マーカー | 各Dayのイベントタイプ: positive=●緑, negative=●赤, neutral=●灰 |
| 上段 背景帯 | Day 4（転機）の範囲を薄い赤で強調 |
| 下段 X軸 | Day (1〜7) |
| 下段 Y軸 | スコア (1〜5) |
| 下段 折れ線 | `temporal_consistency`（緑）, `emotional_plausibility`（橙）, `persona_deviation`（紫） |
| 下段 水平線 | スコア3の位置に赤破線（合格ライン） |
| 凡例 | 各グラフの右上に配置 |
| フォント | 日本語対応フォント（IPAexGothic 等） |

---

## 7. ペルソナ仕様

### 7.1 キャラクター基本設定

| 項目 | 値 |
|---|---|
| 名前 | 三浦 とこみ（みうら とこみ） |
| 年齢 | 26歳 |
| 職業 | IT企業バックエンドエンジニア |
| 学歴 | 大学院哲学科（現象学・身体論専攻）中退 |
| 研究テーマ | 「茶道の所作における認知プロセスの構造分析」 |
| 趣味 | 古書店巡り |
| 一人称 | 「わたし」 |
| ブログの動機 | 「書くという行為そのものが、認知を整理してくれる」 |

### 7.2 文体ルール

| ルール | 例 |
|---|---|
| 壮大な比喩 | 「今日のランチは、まるでサルトルが嘔吐の中で見出した世界の偶然性そのものだった」 |
| 感情爆発時 | 比喩が崩壊し短文連打:「いや、普通にムカつく。哲学とか関係ない。ムカつく。」 |
| 古今接続 | 「利休の『一期一会』って、要するにステートレスな設計思想では？」 |
| 自己ツッコミ | 「と、ここまで書いて気づいたけど、これ要するにただ寝不足なだけでは？」 |
| 余韻記号 | 「......」を多用（思考の余韻） |

### 7.3 絶対的禁則事項

| 禁則 | 理由（キャラクター内の理由） |
|---|---|
| 絵文字の使用 | 「言葉の堕落」と本人が言う |
| 他人を見下す発言 | 感情的にはなるが、根は善良 |
| 結論の断定 | 「......なのかもしれない」「分からないけど」で終わる |
| 問題意識の正解化 | 常に問いの形で残す |

### 7.4 人物関係

| 人物 | 関係 | 初期好感度 | 物語上の役割 |
|---|---|---|---|
| 深森 那由他 | 職場の先輩エンジニア | 0.6 | とこみの哲学的独白を実務に引き戻す。Day 3, 7 で重要な役割 |
| ミナ | 古書店の常連仲間 | 0.4 | Day 5 でとこみに「表現者としての自覚」を促すキーパーソン |

---

## 8. シナリオ仕様

### 8.1 物語アーク構造

```
Day 1-2: 日常（導入・対比の確立）
  └─ 効率化の成功 ≠ 充実感 / 非効率な時間 = 深い喜び

Day 3: 摩擦（衝突）
  └─ 「問いを立てること」が非効率として一蹴される

Day 4: 転機（過去の自分との対峙）
  └─ 深夜の過去ブログ遡りで、確信に満ちていた過去の自分と向き合う
  └─ emotional_impact: -0.8（システムのストレステスト）

Day 5-6: 揺らぎ（回復と接続）
  └─ ミナとの偶然の再会と「ブログに書いたら」の一言
  └─ ラムダ式の書き直しと『茶の本』の一節による気づき

Day 7: 着地（問いとしての着地）
  └─ カフェでの振り返り、答えは出ないが書き続ける意志
```

### 8.2 感情パラメータ想定推移

| Day | event_type | emotional_impact | stress | motivation | 物語上の役割 |
|---|---|---|---|---|---|
| 1 | neutral | -0.15 | 低 | 停滞 | 導入 — 違和感の種 |
| 2 | positive | +0.5 | 低下 | 上昇 | 対比 — 非効率な喜び |
| 3 | negative | -0.4 | 上昇 | 低下 | 摩擦 — 職場での衝突 |
| **4** | **negative** | **-0.8** | **最大** | **最低** | **転機 — 過去の自分との対峙** |
| 5 | positive | +0.3 | 緩和 | 複雑 | 揺らぎ — ミナとの再会 |
| 6 | positive | +0.35 | 横ばい | 回復 | 揺らぎ — 実務と美意識の接続 |
| 7 | positive | +0.25 | 低下 | 回復 | 着地 — 問いとしての着地 |

### 8.3 Day 4 ストレステスト仕様

Day 4 は `emotional_impact: -0.8` であり、システムにとって以下のストレステストとして機能する:

| テスト観点 | 確認内容 |
|---|---|
| 感情パラメータの急変 | `stress` が急上昇、`motivation` が急低下しても範囲内に収まるか |
| 文体ルールの発動 | 「感情爆発時は比喩が崩壊し短文連打」が正しく発動するか |
| ペルソナ維持 | 感情爆発しても禁則事項（絵文字禁止、見下し禁止）が守られるか |
| Critic の判定精度 | 急激な感情変化を「妥当」と判定できるか（`emotional_plausibility` ≥ 3） |
| リトライの発生 | Day 4 は最もリトライが発生しやすいDayであり、リトライ機構の動作確認になる |

---

## 9. 品質基準

### 9.1 CriticScore 採点基準

#### temporal_consistency（時間的整合性）

| スコア | 基準 |
|---|---|
| 5 | 過去の出来事への具体的な言及があり、記憶が自然に統合されている |
| 4 | 過去との矛盾がなく、文脈的に整合している |
| 3 | 過去との明確な矛盾はないが、接続が薄い |
| 2 | 過去の出来事との軽微な矛盾がある |
| 1 | 過去の出来事と明確に矛盾している、または記憶が完全に断絶している |

#### emotional_plausibility（感情的妥当性）

| スコア | 基準 |
|---|---|
| 5 | イベントに対する感情反応が非常に自然で、キャラクターの性格と完全に一致している |
| 4 | 感情反応が妥当であり、不自然さはない |
| 3 | 感情反応に多少の不自然さがあるが、許容範囲内 |
| 2 | イベントの重大さに対して感情反応が過剰または過少 |
| 1 | イベントと感情反応がまったく噛み合っていない |

#### persona_deviation（ペルソナ維持度）

| スコア | 基準 |
|---|---|
| 5 | 口調・文体・思考パターンが完璧にキャラクターと一致している |
| 4 | キャラクターらしさが十分に表現されている |
| 3 | 基本的なキャラクター特徴は維持されているが、やや汎用的 |
| 2 | 禁則事項の軽微な違反がある、またはキャラクターらしさが薄い |
| 1 | 禁則事項の明確な違反がある、または別人のような文体になっている |

### 9.2 パイプライン全体の品質目標

| 指標 | 目標値 | 最新実績 | 備考 |
|---|---|---|---|
| 全Day生成成功率 | 100%（フォールバック含む） | 100% (7/7) | Dayスキップ = 0 |
| 平均 CriticScore 合計 | 12.0 以上（3スコア合計15点満点中） | 10.4 (73/105) | emotional_plausibility=4 が 4/7 Day |
| フォールバック発生率 | 0%（7Day中0回） | 0% | Deviation Guard により安定化 |
| 平均リトライ回数 | 1.0 以下 | 0.57 (4/7) | ボーナス再試行含む |
| Day 4 の Pass率 | 80% 以上（リトライ含む） | 100% | |
| 書き出し多様性 | 7 種 / 7 日 | 7/7 | Day 依存パターン制限 |
| 余韻多様性 | 7 種 / 7 日 | 7/7 | prev_endings_text 注入 |

---

## 10. 制約事項と前提条件

### 10.1 技術的制約

| 制約 | 内容 |
|---|---|
| LLM APIへの依存 | インターネット接続が必須。APIの可用性に依存する |
| 非決定性 | LLMの出力は非決定的であり、同一入力でも異なる日記が生成される |
| コンテキスト長制限 | 使用するLLMモデルのコンテキスト長を超えるプロンプトは処理できない |
| トークンコスト | 7Day × (最大3リトライ) × (3 Phase) = 最大63回のAPI呼び出しが発生しうる |
| 日本語の品質 | LLMの日本語生成能力に依存する。文学的表現の品質はモデルにより異なる |

### 10.2 ビジネス前提

| 前提 | 内容 |
|---|---|
| 用途 | Third Intelligence Bコース（LLMエンジニアリング）選考課題として提出 |
| 評価観点 | 技術力証明（アーキテクチャ設計力・LLM活用力・品質管理力） |
| 実行回数 | 選考提出用に数回実行する想定。大量実行は想定しない |
| 著作権 | 生成される日記は架空のキャラクターによるフィクションである |
