# 設計: LLMClient

## 実装アプローチ
- `architecture.md` §8.3 のインターフェース定義に準拠
- `AsyncOpenAI` クライアントをコンストラクタで生成し、インスタンス変数として保持
- `generate_structured` は `response_format` に Pydantic モデルを使用し Structured Outputs で呼び出す
- `generate_text` は `response_format` なしでプレーンテキスト生成
- ログは `logging.getLogger(__name__)` で DEBUG レベルにトークン数等のメタ情報を記録
- API キーはログに出力しない

## 変更対象ファイル
| ファイル | 変更内容 |
|---|---|
| `csdg/engine/llm_client.py` | 新規作成 — LLMClient ABC + OpenAIClient |
| `tests/test_llm_client.py` | 新規作成 — インスタンス化テスト |

## 代替案と選定理由
- **案A: instructor ライブラリ使用** — 却下。依存を最小限に保つため、openai ライブラリの Structured Outputs をネイティブに使用
- **案B: 同期 API** — 却下。architecture.md の設計方針に従い async で統一
