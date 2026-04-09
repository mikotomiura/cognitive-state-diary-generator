---
description: >
  新規タスクの作業を開始する。.steering/[YYYYMMDD]-[task-name]/ を作成し、
  3問のヒアリングで requirement.md を初期化する。実装作業の前に必ず最初に実行する。
allowed-tools: Write, Bash(mkdir *), Bash(date *), Read
---

# /start-task

## 実行フロー

### Step 1: ヒアリング（3問のみ、1問ずつ）

1. **タスク名**: kebab-case で簡潔に（例: `fix-login-bug`, `add-csv-export`）
2. **ゴール**: このタスクで達成したいことを 1〜3 文で
3. **種類**: `feat`（新機能）/ `fix`（バグ修正）/ `refactor`（リファクタリング）

### Step 2: ディレクトリ作成

```bash
date +%Y%m%d
mkdir -p .steering/[YYYYMMDD]-[task-name]
```

### Step 3: 作業記録の初期化

ヒアリング回答を元に Write で以下を作成:

- `requirement.md` — 背景・ゴール・受け入れ条件を記入
- `design.md` — 空ファイル（実装前に記入）
- `tasklist.md` — 空ファイル（実装前にタスク分解）

### Step 4: 次のコマンドを案内

- `feat` → `/implement feat`
- `fix` → `/implement fix`
- `refactor` → `/implement refactor`

## 制約

- 3問を同時に聞かない（1問ずつ待つ）
- requirement.md の記入を省略しない
- CLAUDE.md の `.steering/` 運用ルールに従う
