---
description: >
  タスクの完了処理。.steering の最終化、テスト実行、コミット提案を行う。
  /implement の完了後に必ず実行する。
allowed-tools: Read, Edit, Bash(git *), Task
---

# /finish-task

## 実行フロー

### Step 1: tasklist の最終確認

`.steering/[現在のタスク]/tasklist.md` を Read で確認。
未完了タスクがあればユーザーに確認: 完了させるか、繰越にするかを選ぶ。

### Step 2: 作業記録の最終化

- `design.md` — 実装中に変わった点を追記
- ブロッカーがあれば `blockers.md`、重要判断があれば `decisions.md` を作成

ユーザーに尋ねる:
> 「特筆すべきブロッカーや設計判断はありましたか?」

### Step 3: テスト実行

`test-runner` を起動 → 全テスト Pass を確認。
失敗があれば完了処理を中断して修正する。

### Step 4: コミットメッセージの提案

```
[type]: [短い説明]

- 変更内容 1
- 変更内容 2

Refs: .steering/[YYYYMMDD]-[task-name]/
```

type: `feat` / `fix` / `refactor` / `docs` / `test` / `chore`

### Step 5: コミット実行

ユーザー承認後に `git commit` を実行。

### Step 6: 完了通知

次のタスクを始める前に `/clear` でセッションをリセットすることを推奨。

## 制約

- テストが失敗している状態で完了しない
- ユーザー承認なしで commit しない
- .steering 記録を省略しない
