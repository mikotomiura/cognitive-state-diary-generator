# 設計: プロンプトファイル作成

## 実装アプローチ
- `.claude/skills/skills/prompt-engineering/examples.md` のテンプレートをベースに、`functional-design.md` §7（ペルソナ仕様）・§9.1（採点基準）の詳細を反映
- `architecture.md` §6.1 の注入順序に合わせてプレースホルダを配置
- `glossary.md` の用語定義に従い用語を統一

## 変更対象ファイル
| ファイル | 変更内容 |
|---|---|
| `prompts/System_Persona.md` | 新規作成 — キャラクター不変ルール |
| `prompts/Prompt_StateUpdate.md` | 新規作成 — Phase 1 状態遷移指示 |
| `prompts/Prompt_Generator.md` | 新規作成 — Phase 2 日記生成指示 |
| `prompts/Prompt_Critic.md` | 新規作成 — Phase 3 評価基準 |

## 代替案と選定理由
- **案A: テンプレートをそのまま使用** — 却下。examples.md のテンプレートは骨格のみであり、口調の良い例/悪い例、禁則の悪い例、5段階採点基準の詳細が不足
- **案B: テンプレートを拡張して使用（採用）** — examples.md の構造を踏襲しつつ、functional-design.md の詳細仕様を反映して拡充
