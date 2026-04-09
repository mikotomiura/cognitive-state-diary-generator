---
description: >
  直近の git 変更を動的に取得し、code-reviewer と security-checker を並列起動して
  結果を統合報告する。コミット前・PR 作成前に実行する。
allowed-tools: Read, Bash(git *), Task
---

# /review-changes

## 現在の状況
!`git status --short`

## 変更統計
!`git diff --stat HEAD`

---

## 実行フロー

### Step 1: 変更の確認

上記が空の場合: 「変更がありません。終了します。」

### Step 2: 並列レビュー

以下を **同時に** 起動する:

- `code-reviewer` → 「直近の git diff をレビュー。HIGH/MEDIUM 指摘を優先して報告」
- `security-checker` → 外部入力・認証・認可に関わる変更がある場合のみ起動

### Step 3: 統合レポート

両エージェントの結果をまとめて以下の形式で表示:

```
## 変更レビュー結果
- 変更ファイル: N個  追加: +N  削除: -N

### CRITICAL/HIGH（必須対応）
[統合した指摘]

### MEDIUM（推奨対応）
[統合した指摘]

### 良かった点
[評価した点]
```

### Step 4: 判定

- CRITICAL/HIGH あり → 「修正後に `/review-changes` を再実行してください」
- なし → 「commit 可能です」

## 制約

- 生のエージェントレポートをそのまま流さない（必ず統合・要約する）
- 変更がなければ実行しない
