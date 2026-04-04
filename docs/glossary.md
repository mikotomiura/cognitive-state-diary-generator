# ユビキタス言語定義 (Glossary)

> **目的:** CSDG プロジェクトにおいて、チームメンバー・ドキュメント・コード・プロンプトすべてで統一された用語を使用するための定義書。
> 曖昧な表現を排除し、「この言葉はこの意味でしか使わない」という共通認識を確立する。

---

## 1. システムアーキテクチャ用語

### CSDG (Cognitive-State Diary Generator)
体系的認知モデルに基づくAIキャラクター日記生成システムの正式名称。
「認知状態日記生成器」と訳す。LLMを用いて、構造化された感情状態の遷移に基づき、一貫性のあるキャラクターのブログ日記を7日間分生成する。

### パイプライン (Pipeline)
1日分の日記を生成するための3フェーズの処理フロー全体を指す。
Phase 1（状態遷移）→ Phase 2（コンテンツ生成）→ Phase 3（Critic評価）の一連の流れ。
このパイプラインを7回（Day 1〜Day 7）ループさせることで、1週間分の日記が生成される。

### Phase（フェーズ）
パイプラインを構成する処理の単位。以下の3つが存在する:
- **Phase 1: 状態遷移 (State Update)** — イベントに基づきキャラクターの内部状態を更新する
- **Phase 2: コンテンツ生成 (Content Generation)** — 更新された状態に基づきブログ本文を生成する
- **Phase 3: Critic評価 (Critic Evaluation)** — 生成された日記を定量的に評価し、品質基準を満たさない場合はリトライする

### Actor（アクター）
日記の「生成」を担当するLLMの役割。Phase 1では内部状態の更新、Phase 2では日記本文の生成を行う。
Criticからのフィードバック（`revision_instruction`）を受けて再生成を行うこともある。
**注意:** 強化学習のActorとは異なり、実際の勾配計算は行わない。アナロジーとしての命名である。

### Critic（クリティック）
日記の「評価」を担当するLLMの役割。Phase 3で、Actorが生成した日記を3つの観点（時間的整合性・感情的妥当性・ペルソナ維持度）から定量評価する。
スコアが基準未満の場合、`revision_instruction`（修正指示）をActorに返す。
**注意:** 強化学習のCriticとは異なり、実際の価値関数の計算は行わない。

### Actor-Critic型 敵対的検証ループ
生成（Actor）と評価（Critic）を分離し、相互にフィードバックさせることで品質を担保するアーキテクチャパターン。
ActorとCriticは異なるプロンプト（異なる「人格」）で動作し、Criticは厳格な編集者・心理学者として振る舞う。

---

## 2. データモデル用語

### DailyEvent（日次イベント）
1日に起きる出来事を構造化したデータモデル。Pydantic `BaseModel` として定義される。
シナリオ設計時に事前定義され、パイプラインの入力として使用される。
- `day`: 経過日数（1〜7）
- `event_type`: イベントの種類（`positive` / `negative` / `neutral`）
- `domain`: イベントの領域（`仕事` / `人間関係` / `趣味` / `内省` / `思想`）
- `description`: 出来事の客観的な記述
- `emotional_impact`: 感情的インパクト（-1.0〜+1.0）

### CharacterState（キャラクター内部状態）
ある時点でのキャラクターの感情・記憶・関心事を構造化したデータモデル。
時刻 `t` における状態を `h_t` と表記する。初期状態は `h_0`。
- **連続変数:** `fatigue`（疲労度: 0.0〜1.0）, `motivation`（モチベーション: -1.0〜1.0）, `stress`（ストレス値: -1.0〜1.0）
- **離散変数:** `current_focus`（現在の関心事）, `unresolved_issue`（未解決の課題）, `growth_theme`（成長テーマ）
- **累積記憶:** `memory_buffer`（過去3日分のサマリ）, `relationships`（人物への好感度）

### HumanCondition（人間的コンディション）
`CharacterState` のサブモデルとして保持される、イベント非依存の生物的・心理的状態。
日次イベントの感情インパクトとは独立に変動し、日記の「人間的深度」を制御する。
- `sleep_quality`（睡眠の質: 0.0〜1.0）: 前日の fatigue/stress から導出。低値は文体の散漫さに影響
- `physical_energy`（身体的エネルギー: 0.0〜1.0）: sleep_quality と fatigue から導出。motivation に負の補正を与える
- `mood_baseline`（気分ベースライン: -1.0〜1.0）: イベント非依存の気分の慣性。ランダムドリフトで緩やかに変動
- `cognitive_load`（認知負荷: 0.0〜1.0）: unresolved_issue の存在やストレスにより上昇。高値は思考の断片化に影響
- `emotional_conflict`（感情的葛藤: Optional[str]）: 矛盾する感情シグナルの同時発生を記述

### h_t（潜在変数 / 内部状態ベクトル）
時刻 `t` における `CharacterState` のインスタンスを指す数学的表記。
`h_{t-1}` は前日の状態、`h_0` は初期状態を意味する。
**コード上では** `CharacterState` オブジェクトとして扱う。変数名には `state` または `current_state` を使用する。

### CriticScore（評価器スコア）
Criticが出力する評価結果のデータモデル。以下の3つのスコア（各1〜5）と診断用フィールドで構成される:
- `temporal_consistency`（時間的整合性）: 過去の日記・状態との矛盾がないか
- `emotional_plausibility`（感情的妥当性）: イベントに対する感情変化が自然か
- `persona_deviation`（ペルソナ維持度）: キャラクター設定からの逸脱がないか
- `hook_strength`（フック強度）: 0.0〜1.0 の診断専用フィールド。日記末尾の「続きを読みたい」度を測定。Pass/Reject判定には使用されない
- `reject_reason`: リジェクト時の理由（Optional）
- `revision_instruction`: 修正指示（Optional）

**合格基準:** 全スコア（`temporal_consistency`, `emotional_plausibility`, `persona_deviation`）が3以上で Pass。1つでも3未満があれば Reject。`hook_strength` は判定に影響しない。

### EMOTION_SENSITIVITY（感情感度係数）
イベントの `emotional_impact` に対して各感情パラメータがどの程度反応するかを定義するハイパーパラメータ。
`config.py` で管理され、Criticが感情変化の妥当性を検証する際の期待値算出に使用される。

```python
EMOTION_SENSITIVITY = {
    "stress": -0.45,
    "motivation": 0.4,
    "fatigue": -0.2,
}
```

### expected_delta（期待変動幅）
`event.emotional_impact * EMOTION_SENSITIVITY["パラメータ名"]` で算出される、感情パラメータの期待される変動量。
Criticがこの値とActorの実際の出力を比較し、乖離が大きい場合にRejectする。

### deviation（乖離）
Actorが生成した実際の感情パラメータ変化量と `expected_delta` の差分。
Criticのプロンプトに注入され、評価の根拠として使用される。

---

## 3. メモリ管理用語

### スライディングウィンドウ (Sliding Window Memory)
`CharacterState.memory_buffer` に保持される直近3日分の日記サマリのこと。
Day 4の生成時には Day 1〜3 のサマリが、Day 5の生成時には Day 2〜4 のサマリが保持される。
古い記憶は自動的に押し出される（FIFO方式）。

### エピソード記憶 (Episodic Memory)
`memory_buffer` に格納される個別の日のサマリ情報。各Dayの処理完了時に、そのDayの要約が1つのエピソードとして追加される。

### 意味記憶 (Semantic Memory)
キャラクターの不変の性格・口調・禁則事項など、時間経過で変化しない情報。
`System_Persona.md` として定義され、すべてのLLM呼び出しのシステムプロンプトに常に含まれる。

### ShortTermMemory（短期記憶）
直近の日記テキスト要約を保持するメモリ層。`window_size`（デフォルト3）件のスライディングウィンドウで管理される。`CharacterState.memory_buffer` として Actor に渡される。

### LongTermMemory（長期記憶）
LLM による抽出で蓄積される信念（`beliefs`）、繰り返しテーマ（`recurring_themes`）、物語上の転換点（`turning_points`）を保持するメモリ層。Actor の `long_term_context` として注入される。

### MemoryManager（メモリマネージャ）
`ShortTermMemory` と `LongTermMemory` を統合管理するクラス。Day 完了後に `update_after_day()` で両層を更新する。

### コンテキストウィンドウの汚染 (Context Window Pollution)
過去の生成テキストをプロンプトに累積的に結合することで、LLMの注意が分散し、品質が劣化する現象。
本システムでは、エピソード記憶の分離とスライディングウィンドウにより、この問題を防止する。

---

## 4. 品質管理・リトライ用語

### Pass / Reject
CriticによるPhase 3の判定結果。全スコアが3以上なら **Pass**（合格）、1つでも3未満なら **Reject**（不合格）。

### revision_instruction（修正指示）
Reject時にCriticが出力する、Actorへの具体的な修正指示テキスト。
次回のリトライ時にActorのプロンプトに注入される。

### Temperature Decay（温度減衰）
リトライ時にLLMの Temperature パラメータを区分線形スケジュールで段階的に下げる戦略。
- 1回目: 0.70（多様性を持たせて生成）
- 2回目: 0.60（十分な多様性を維持）
- 3回目: 0.45（やや保守的に）
- 4回目: 0.30（決定論的に）

### Best-of-N（ベスト・オブ・N）
最大リトライ回数（3回）を超えても合格しない場合のフォールバック戦略。
全リトライの中で `CriticScore` の合計値が最も高いペアを強制採用する。

### Self-Healing（自己修復）
LLMの出力パースエラー（JSONの不正な構造化出力）や、リトライ上限超過時に、システムがクラッシュせずに安全な状態に復帰する機構の総称。
例: `ValidationError` 発生時に前日の状態をコピーし、暫定サマリを挿入するフォールバック。

### Deviation Guard（偏差ガード）
Phase 1 (State Update) 完了後に deviation を即座に計算し、`max_dev > 0.10` の場合に
actual values を expected_delta 方向に α=0.5 でソフトブレンド補正する機構。
Phase 2/3 リトライでは `final_state` の deviation は修正不能であるため、
Phase 1 段階で deviation 超過を防止する。`pipeline.py` の `_DEVIATION_GUARD_THRESHOLD` と
`_DEVIATION_GUARD_ALPHA` で制御される。

### prev_endings_text（過去の余韻テキスト注入）
過去の日記の余韻（末尾段落）原文を Generator プロンプトに注入し、テキストレベルの余韻重複を
事前に回避する機構。`prev_openings_text`（冒頭テキスト注入）と対をなす。

### prev_day_ending（前日の末尾テキスト）
前日の日記末尾段落を Generator および Critic の両プロンプトに注入する機構。
Generator では Day 2以降の冒頭で前日の出来事・感情・人物に具体的に言及させ、
Critic では前日フックの回収状況を検証する（hook_strength の採点に影響）。
`prev_endings`（複数日の蓄積リスト）や `prev_endings_text`（テキスト重複回避用リスト）と異なり、
直近1日分のみを参照する。`pipeline.py` の `_extract_ending()` で抽出される。

### hook_strength（フック強度）
CriticScore の診断専用フィールド（0.0〜1.0）。日記末尾の「未解決フック」の強度を測定する。
余韻（読後感を残す表現、文章を閉じる効果）とフック（読者が続きを気にする要素、文章を開く効果）を区別し、
フックの有無と強度を定量化する。Pass/Reject 判定には使用されず、`generation_log.json` への記録のみに使用される。
Layer 3 (LLMJudge) が評価し、`_compute_final_score()` で最終スコアに転送される。

### フォールバック (Fallback)
エラー発生時に実行される代替処理。Self-Healingの具体的な実装を指す。
本システムでは以下のフォールバックが定義されている:
- **Phase 1:** 前日の `CharacterState` をコピーし、`memory_buffer` に暫定サマリを挿入
- **Phase 3:** Best-of-N による強制採用

### Veto権 (Veto)
Critic Layer 1（RuleBasedValidator）が致命的違反を検出した際に、該当軸のスコアに上限キャップを強制適用する機構。
禁止一人称の使用（persona 軸）、文字数レンジ逸脱（全軸）、trigram overlap 50%超（temporal 軸）が対象。
`config.py` の `VetoCaps` で上限値を設定可能。

### prev_endings（余韻フィードバック）
直近3日分の日記の末尾段落を蓄積し、Generator プロンプトに注入することで余韻フレーズの反復を防止する仕組み。
`pipeline.py` の `_extract_ending()` で抽出される。

### prev_images（シーン描写の反復防止）
日記テキストから場所・物のマーカー語を含むキーフレーズを Day 間で蓄積し、Generator プロンプトに「使用済みシーン描写」として注入することで、イメージの使い回しを抑制する仕組み。
`pipeline.py` の `_extract_key_images()` で抽出される。

### used_openings（書き出しパターンの多様化）
日記の冒頭を比喩型 / 五感型 / 会話型 / 問い型 / 断片型 / 回想型の6パターンに自動分類し、Day 間で蓄積して Generator プロンプトに注入することで書き出しの単調化を防止する仕組み。
`pipeline.py` の `_detect_opening_pattern()` で分類される。

### used_ending_patterns（余韻構文パターンの多様化）
日記の余韻（末尾段落）の構文パターンを「〜だろう系 / 〜かもしれない系 / 〜ずにいる系 / 〜ている系 / 行動締め系 / 引用系 / 体言止め系 / 省略系 / その他」の9パターンに自動分類し、Day 間で蓄積する。Generator プロンプトには**使用可能パターンと具体例のホワイトリスト**として注入し、LLM の余韻多様性を誘導する。
`pipeline.py` の `_detect_ending_pattern()` で分類される。同一パターンの2回以上の使用を禁止する。

### theme_word_totals（主題語頻度の累計制御）
主題語（「効率」「非効率」「最適化」「自動化」等）の7日間累計使用回数を追跡し、閾値超過時に Generator プロンプトへ使用制限を注入することで主題語の過剰使用を防止する仕組み。
`pipeline.py` の `_count_theme_words()` でカウントされる。ソフトリミット（10回）超過で per-day 制限を強化、ハードリミット（18回）超過で使用禁止を注入する。イベント記述に主題語が含まれる場合は代替表現への置き換えを明示的に警告する。

### prev_rhetorical（修辞疑問文の反復防止）
日記本文中の修辞疑問文（「〜って、何に対して？」等）を抽出・蓄積し、Generator プロンプトに「使用済み修辞疑問文」として注入することで、Day 間の問いかけパターンの反復を防止する仕組み。
`pipeline.py` の `_extract_rhetorical_questions()` で抽出される。直近5件を保持する。

### critical_constraints（冒頭禁止事項）
過去の使用状況に基づく絶対禁止事項を Generator プロンプトの**冒頭**に配置する仕組み。以下の項目が動的に注入される:
- **文字数厳守:** 本文300-350文字（実生成380-420文字を狙う）
- **読者語りかけ必須:** 問いかけ・共感・弁明など最低1回
- **感情決壊モード:** `|emotional_impact| > 0.7` の日に短文連打・口語・比喩崩壊・タイトル崩壊を強制
- **構造的禁止事項:** 余韻パターン・場面構造・書き出しパターンの上限到達や前日同一構造
`actor.py` の `_build_generator_prompt()` で組み立てられ、`Prompt_Generator.md` の `{critical_constraints}` プレースホルダに展開される。

### _validate_structural_constraints（構造的制約バリデーション）
Phase 2 生成直後に実行される軽量なルールベースチェック。余韻パターン上限・場面構造の連続使用/上限・主題語 per-day 上限・書き出しパターン上限・禁止余韻パターン・本文フレーズの Day 間重複・**文字数の理想範囲 (450文字以下)**の項目を検査し、違反メッセージのリストを返す。
Critic（Phase 3）が検査しない構造的多様性を補完する。構造違反がある場合は Critic Pass 時でも1回だけ再試行を強制する。

### 高インパクト日文体検証 (High-Impact Style Check)
`StatisticalChecker` が `|emotional_impact| > 0.7` の高インパクト日に対して、感情的な文体特徴（短文連打・口語混入・哲学中断）を検証する機構。
短文連打は **8文字以下の文が3回以上連続** するパートが1箇所以上必要。整然とした文体の場合は `persona_deviation` を段階的に減点する (features<2: -2.5, features<3: -1.0)。

---

## 5. プロンプト管理用語

### プロンプトモジュール (Prompt Module)
`prompts/` ディレクトリに配置されるMarkdownファイル。役割ごとに分離されている:
- `System_Persona.md` — キャラクターの不変ルール（意味記憶）
- `Prompt_StateUpdate.md` — Phase 1: 状態遷移の計算ルール
- `Prompt_Generator.md` — Phase 2: 日記生成の構成・言語化ルール
- `Prompt_Critic.md` — Phase 3: 評価基準・採点基準
- `Prompt_MemoryExtract.md` — 長期記憶の信念・テーマ抽出
- `System_MemoryManager.md` — メモリ管理システムプロンプト

### ペルソナ破綻 (Persona Deviation)
キャラクター設定からの逸脱。以下が典型的なペルソナ破綻:
- 絵文字の使用（禁則事項違反）
- 断定的な結論（「......なのかもしれない」で終わらない）
- 他人を見下す発言
- キャラクターの知識・経験にない専門用語の使用

---

## 6. シナリオ・物語用語

### 物語アーク (Narrative Arc)
7日間の日記全体を貫く物語構造。本プロジェクトでは「効率の果てに、立ち止まる」をテーマとし、「日常→転機→揺らぎ→着地」の4段構成をとる。

### 意図的な非効率 (Intentional Inefficiency)
本システムの思想的核心概念。効率化が至上命題とされる現代において、あえて非効率なプロセス（手作業・所作・思索）に価値を見出す思想。
キャラクター（三浦とこみ）はDay 7においてもこの概念を完全には言語化できておらず、「問い」として残される。

### emotional_impact（感情的インパクト）
`DailyEvent` のフィールド。-1.0（強いネガティブ）〜 +1.0（強いポジティブ）の範囲で、イベントがキャラクターに与える感情的衝撃の強さを数値化したもの。

### 転機 (Turning Point)
物語アークにおいてキャラクターの内面に不可逆的な変化が生じるイベント。
本シナリオでは Day 4（`emotional_impact: -0.8`）が該当する。

---

## 7. キャラクター用語

### 三浦 とこみ（みうら とこみ）
本システムの主人公キャラクター。26歳、元大学院哲学科（現象学・身体論専攻）中退、IT企業バックエンドエンジニア。
一人称は「わたし」。**コード上・プロンプト上で「主人公」「ユーザー」等の別称を使わないこと。必ず「とこみ」と呼ぶ。**

### 深森 那由他（ふかもり なゆた）
とこみの職場の先輩エンジニア。面倒見が良く、とこみの哲学的独白を実務レベルに引き戻す役割。
`relationships` の初期好感度: `0.6`

### ミナ
古書店の常連仲間。認知科学や東洋哲学に詳しい。物語の転機においてキーパーソンとなる。
Day 5でとこみに「表現者」としての自覚を促す。
`relationships` の初期好感度: `0.4`

---

## 8. 出力・可視化用語

### 成果物ファイル (Output Files)
パイプラインの最終出力。`output/day_01.md` 〜 `output/day_07.md` として個別に保存されるブログ日記テキスト。

### 実行ログ (Generation Log)
`output/generation_log.json` として保存される、パイプライン実行の完全な追跡記録。
各Phaseの入出力、CriticScore、リトライ回数、フォールバック発生有無を含む。

### 状態推移グラフ (State Trajectory)
`output/state_trajectory.png` として保存される、7日間の `stress` / `motivation` / `fatigue` の推移およびCriticScoreの変動グラフ。

---

## 9. 開発プロセス用語

### .steering（ステアリング）
作業セッションごとの構造化ノートを格納するディレクトリ。
`[YYYYMMDD]-[タスク名]/` 単位で作業記録を管理する。

### スラッシュコマンド (Slash Command)
`.claude/commands/` に定義される、頻繁に使用するワークフローをコマンド化したもの。
例: `/add-feature`, `/fix-bug`, `/refactor`

### サブエージェント (Sub-Agent)
`.claude/agents/` に定義される、特定の専門タスクに特化したエージェント。
親エージェントから呼び出され、詳細な作業を実行後、簡潔なレポートを返す。

### スキル (Skill)
`.claude/skills/` に定義される、特定分野のベストプラクティスや規約を記述したドキュメント。
Claude Codeがコーディング・テスト・プロンプト設計を行う際の判断基準として参照する。

---

## 10. 思想的基盤用語

### Extract-Reverify-Reimplement-Express (ERRE)
本プロジェクトの思想的フレームワーク:
- **Extract（抽出）:** 古い思想から「人間の思考を深化させる構造」を仮説として取り出す
- **Reverify（再検証）:** 抽出した仮説を現代科学の手法で再検証する
- **Reimplement（再実装）:** 検証された知見をシステムとして動作可能な形に落とし込む
- **Express（表現）:** 再実装された知見を、人に伝わる形で表現する

### Neuro-symbolicアプローチ
LLMの定性的判断（言語による評価）と、プログラムによる定量的計算（expected_deltaの算出）を組み合わせる手法。
Criticの評価に数学的な裏付けを持たせるために採用されている。

---

## 用語の使用ルール

1. **コード内の変数名・関数名は英語表記を使用する。** ただし、コメントやdocstringでは日本語でこの用語集の定義に従って説明する。
2. **プロンプト内では日本語表記を使用する。** ただし、技術用語（Actor, Critic, Phase等）はカタカナまたは英語をそのまま使う。
3. **ドキュメント内では、初出時に英語表記と日本語表記を併記する。** 2回目以降はどちらか一方で統一する。
4. **この用語集に定義されていない専門用語を新たに導入する場合は、まずこのファイルに追加してから使用する。**
