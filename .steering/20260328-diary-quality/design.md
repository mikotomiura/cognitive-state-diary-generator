# 設計: 日記品質改善

## 問題分析

### 1. イメージ反復 (Critical)
- 「電車の窓に映る自分の顔」(Day 3 & 5), 「缶コーヒー」(Day 5 & 7) 等
- **原因:** LLM が前日までに使った場面描写を知らない。memory_buffer は 100 文字に切り詰められ、イメージ情報が失われている

### 2. 書き出しパターン反復 (Warning)
- 比喩型「今日は、まるで...」が 3 回 (Day 1, 3, 7)
- **原因:** パターンの使用回数をパイプラインが追跡していない

### 3. 構造の単調さ (Warning)
- 7 日中 5 日が「仕事→反応→移動→古書店→問い→余韻」の同一構造
- **原因:** ペルソナ設定 (古書店好き) + プロンプトに構造バリエーション指示がない

### 4. Day 4 Critic スコア膨張 (Warning)
- emotional_impact=-0.9 で 5/5/5 (Critic プロンプトが「厳しく評価」と指示しているのに)
- **原因:** StatisticalChecker に high-impact 日の文体検証ルールはあるが、LLMJudge がそれを上書きしている

## 実装アプローチ

### A. prev_images 注入 (パイプライン + プロンプト)
- `_extract_key_images()`: 日記テキストからシーンマーカー (場所・物) を含む文を抽出
- `prev_images: list[str]` をDay間で蓄積 (最大5件)
- Generator プロンプトに「使用済みシーン」セクションとして注入

### B. 書き出しパターン追跡 (パイプライン + プロンプト)
- `_detect_opening_pattern()`: 冒頭文からパターンを分類
- `used_openings: list[str]` を蓄積
- Generator プロンプトに「使用済み書き出し」として注入

### C. 構造多様性指示 (プロンプトのみ)
- Prompt_Generator.md に「構造のバリエーション」セクションを追加
- 古書店以外の内省の場 (自室, 通勤電車, カフェ, 公園等) を提示

### D. Critic 感度強化 (プロンプト + コード)
- Prompt_Critic.md に high-impact 日のスコア上限ガイドラインを強化
- StatisticalChecker に emotional_impact > 0.7 時の文体チェック強化

## 変更対象ファイル

| ファイル | 変更内容 |
|---|---|
| `csdg/engine/pipeline.py` | `_extract_key_images`, `_detect_opening_pattern`, 蓄積ロジック |
| `csdg/engine/actor.py` | `generate_diary` に `prev_images`, `used_openings` 引数追加 |
| `prompts/Prompt_Generator.md` | `{prev_images}`, `{used_openings}` プレースホルダ追加 |
| `prompts/Prompt_Critic.md` | high-impact 日のスコア制約強化 |
| `csdg/engine/critic.py` | `StatisticalChecker` に high-impact 文体チェック追加 |
| `tests/test_pipeline.py` | 新関数のテスト追加 |
| `tests/test_actor.py` | 新引数のテスト追加 |
