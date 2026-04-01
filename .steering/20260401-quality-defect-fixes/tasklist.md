# タスクリスト: 品質欠陥6件修正

## 実装タスク
- [x] P0-2: Veto 無効化バグ修正 (critic.py _compute_final_score)
- [x] P0-1a: trigram 関数公開化 (critic.py)
- [x] P0-1b: 冒頭テキスト重複チェック (pipeline.py)
- [x] P0-1c: Actor プロンプト注入 (actor.py)
- [x] P1-1: 書き出しパターン分類精度改善 (pipeline.py)
- [x] P1-2: Temperature Decay 不発修正 (pipeline.py)
- [x] P2-2: 余韻パターン分類精度改善 (pipeline.py)
- [x] P2-1: 高インパクト日文体ガイダンス (Prompt_Generator.md)

## テストタスク
- [x] P0-2: veto バイパステスト追加 (test_critic.py)
- [x] P0-1: 冒頭テキスト抽出テスト追加 (test_pipeline.py)
- [x] P1-1: 分類改善テスト追加 (test_pipeline.py)
- [x] P2-2: 余韻分類改善テスト追加 (test_pipeline.py)

## 検証
- [x] pytest tests/ -v 全 Pass (459 passed)
- [x] mypy csdg/ --strict Pass (no issues)
- [x] ruff check/format Pass
