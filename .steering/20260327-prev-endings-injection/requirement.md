# 要件定義: prev_endings 注入による余韻反復防止

## 背景
3回の全7Day実行で「効率的に生きることと、豊かに生きることは、本当に両立するのだろうか......。」が複数Dayで反復出現。根本原因: LLMが生成時に前日の余韻を参照できない（prev_diaryがgenerate_diaryに渡されていない）。

## 実装内容
直近3Dayの末尾段落（余韻）を抽出・蓄積し、Prompt_Generator.md に注入する。

## 受け入れ条件
- [ ] pipeline.py で余韻を蓄積し generate_diary に渡す
- [ ] actor.py でプロンプトに「過去の余韻（使用済み）」セクションとして注入
- [ ] Prompt_Generator.md に {prev_endings} プレースホルダ追加
- [ ] テスト追加・全テスト Pass
- [ ] 全7Day実行で余韻の重複が解消

## 影響範囲
- csdg/engine/pipeline.py
- csdg/engine/actor.py
- prompts/Prompt_Generator.md
- tests/test_pipeline.py, tests/test_actor.py
