# 要件定義: config.py 実装

## 背景
パイプラインの設定を一元管理する CSDGConfig が必要。
architecture.md §5.2 および functional-design.md §5.4 の仕様に基づく。

## 実装内容
1. CSDGConfig (pydantic-settings BaseSettings)
2. emotion_sensitivity プロパティ
3. temperature_schedule プロパティ

## 受け入れ条件
- [ ] CSDGConfig が定義されている
- [ ] emotion_sensitivity プロパティが動作する
- [ ] temperature_schedule プロパティが動作する
- [ ] テストが全件 Pass
- [ ] mypy, ruff がエラー 0

## 影響範囲
- csdg/config.py (新規)
- tests/test_config.py (新規)
