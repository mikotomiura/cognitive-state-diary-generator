# 設計: Actor モジュール

## 実装アプローチ
- `architecture.md` §3.1, §3.2, §6 に準拠
- `python-standards/examples.md` §4 の Actor パターンを踏襲
- プロンプトは `Path.read_text()` でファイルから読み込み、`.format()` でテンプレート展開
- prompts_dir はコンストラクタで受け取り、テスト時に差し替え可能にする

## 変更対象ファイル
| ファイル | 変更内容 |
|---|---|
| `csdg/engine/actor.py` | 新規作成 - Actor クラス |
| `tests/conftest.py` | 新規作成 - 共通フィクスチャ |
| `tests/test_actor.py` | 新規作成 - Actor のテスト |

## 代替案と選定理由
- **案A: prompts_dir をハードコード** - 却下。テスト時にモックプロンプトを使えない
- **案B: prompts_dir をコンストラクタ引数にする (採用)** - テスタビリティが高い
