---
description: >
  feat / fix / refactor を統合した実装ワークフロー。/start-task の後に
  タイプを指定して実行する（例: /implement feat）。
  file-finder, impact-analyzer, test-runner, code-reviewer を使う。
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(git *), Task
---

# /implement [type: feat | fix | refactor]

## 前提

`/start-task` 完了済み。`.steering/[現在のタスク]/requirement.md` 記入済み。

---

## feat（新機能追加）

### Step 1: 調査
`file-finder` で類似実装を検索。`impact-analyzer` で影響範囲を分析。

### Step 2: ドキュメント先行更新（設計書ファーストの原則）
- `docs/functional-design.md` に機能要件を追記
- `docs/glossary.md` に新規用語を追加（あれば）

### Step 3: 設計と承認
`design.md` に実装アプローチ・変更対象ファイル・テスト戦略を記入し、ユーザー承認を得る。

### Step 4: 実装
`git checkout -b feat/[名前]` 後、`development-guidelines.md` に従い実装。

### Step 5: テストと検証
`test-runner` → 正常系 / 境界値 / 異常系が全 Pass であることを確認。

### Step 6: レビューと完了
`code-reviewer` → HIGH 指摘をすべて対応。`/finish-task` を実行。

---

## fix（バグ修正）

### Step 1: 再現と原因特定
`file-finder` で関連コード特定。ログがあれば `log-analyzer` で確認。
根本原因を `design.md` に記録する。

### Step 2: 回帰テスト追加（Red）
バグを再現するテストを **修正前に** 書く。このテストは必ず失敗するはず。

### Step 3: 最小限の修正（Green）
根本原因のみ修正。ついで修正は含めない。

### Step 4: 検証と完了
`test-runner` → 追加テスト含む全件 Pass を確認。`/finish-task` を実行。

---

## refactor（リファクタリング）

### Step 1: 安全ネット確認
`test-runner` → **全テスト Green の状態から始める。Red があれば開始しない。**

### Step 2: 影響範囲と設計承認
`impact-analyzer` で変更範囲を確認。`design.md` に変更計画を記入し、ユーザー承認を得る。

### Step 3: 段階的変更
変更 → `test-runner` → Pass → `git commit` を小さな単位で繰り返す。

### Step 4: レビューと完了
`code-reviewer` → 振る舞いが変わっていないことを確認。`/finish-task` を実行。

---

## 共通の制約

- 設計承認なしに実装に入らない（feat / refactor）
- テストが Red のまま次ステップに進まない（fix / refactor）
- fix でついで修正・リファクタリングを混ぜない
- 完了後は必ず `/finish-task` を実行する
