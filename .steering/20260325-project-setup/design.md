# 設計: project-setup

## 実装アプローチ
`docs/repository-structure.md` のディレクトリツリーに従い、最小限の初期ファイルを配置する。
パッケージ管理には `uv` を使用し、ビルドバックエンドには `hatchling` を採用する。

## 変更対象ファイル
| ファイル | 変更内容 |
|---|---|
| `csdg/__init__.py` | パッケージ初期化、`__version__ = "0.1.0"` 定義 |
| `csdg/engine/__init__.py` | サブパッケージ初期化 |
| `tests/__init__.py` | テストパッケージ初期化 |
| `pyproject.toml` | プロジェクト定義・依存関係・ruff/mypy/pytest設定 |
| `.env.example` | 環境変数テンプレート |
| `.gitignore` | Git除外ルール |
| `.python-version` | Python 3.11 指定 |

## 代替案と選定理由
- **ビルドバックエンド:** `hatchling` を採用。`setuptools` も候補だが、`uv` との親和性と設定のシンプルさから `hatchling` を選定。
- **ruff select ルール:** CLAUDE.md の指示に従い、E/W/F/I/N/UP/B/SIM/TCH/RUF を選択。
