# 要件定義: main.py + visualization.py 実装

## 背景
パイプラインの CLI エントリポイントと可視化モジュールが未実装。

## 実装内容
1. csdg/main.py: CLI 引数解析、パイプライン実行、日記保存、ログ保存
2. csdg/visualization.py: 感情パラメータ推移 + CriticScore 推移の2段グラフ生成

## 受け入れ条件
- [ ] python -m csdg.main --dry-run が終了コード 0 で完了
- [ ] save_diary が YAML フロントマター付き Markdown を出力
- [ ] generate_state_trajectory がグラフ PNG を生成
- [ ] pytest tests/test_visualization.py -v が全件 Pass
- [ ] mypy --strict エラー 0
- [ ] ruff check エラー 0
