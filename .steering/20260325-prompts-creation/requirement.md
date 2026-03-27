# 要件定義: プロンプトファイル作成

## 背景
CSDG パイプラインの3フェーズ（状態遷移・コンテンツ生成・Critic評価）で使用する4つのプロンプトファイルが未作成。
パイプライン実行の前提条件として、`prompts/` に4ファイルが必要。

## 実装内容
以下の4つのプロンプトファイルを `prompts/` ディレクトリに作成する:
1. `System_Persona.md` — キャラクター「三浦とこみ」の不変ルール（全Phase共通 System Prompt）
2. `Prompt_StateUpdate.md` — Phase 1: 状態遷移の User Prompt
3. `Prompt_Generator.md` — Phase 2: 日記生成の User Prompt
4. `Prompt_Critic.md` — Phase 3: Critic評価の User Prompt

## 受け入れ条件
- [x] 4ファイルが `prompts/` に存在する
- [x] プレースホルダ名が `architecture.md` §6.1 の注入順序と一致している
- [x] ペルソナの口調ルールに良い例・悪い例が含まれている
- [x] ペルソナの禁則事項に「こう書いてはいけない」例が含まれている
- [x] Critic の採点基準が5段階で具体的に記述されている
- [x] `glossary.md` の用語が正しく使用されている
- [x] Python コードがプロンプト内に埋め込まれていない

## 影響範囲
- `prompts/` — 新規ファイル4つ
- `docs/repository-structure.md` — prompts/ セクションの更新（必要に応じて）
