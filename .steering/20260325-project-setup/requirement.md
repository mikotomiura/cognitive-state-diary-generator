# 要件定義: project-setup

## 背景
CSDG プロジェクトの開発を開始するにあたり、リポジトリの初期構造・依存関係・開発ツール設定を整備する必要がある。
`docs/repository-structure.md` に定義されたディレクトリ構成に従い、開発基盤を構築する。

## 実装内容
1. `repository-structure.md` に準拠したディレクトリ構造の作成
2. `pyproject.toml` によるプロジェクト定義・依存関係・ツール設定
3. `.env.example` による環境変数テンプレートの提供
4. `.gitignore` / `.python-version` の設定
5. `uv sync` による依存関係の解決と検証

## 受け入れ条件
- [x] ディレクトリ構造が `docs/repository-structure.md` と一致している
- [x] `pyproject.toml` に必要な依存関係とツール設定が記述されている
- [x] `.env.example` に全環境変数テンプレートが記述されている
- [x] `.gitignore` に必要な除外ルールが記述されている
- [x] `uv sync` が成功する

## 影響範囲
- リポジトリルート全体（新規作成のため既存への影響なし）
