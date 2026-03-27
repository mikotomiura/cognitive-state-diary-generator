# 要件定義: scenario.py 実装

## 背景
パイプラインの入力となる7日分の DailyEvent と初期状態 (h_0) を定義する必要がある。
functional-design.md §8 のシナリオ仕様に基づく。

## 実装内容
1. 7日分の DailyEvent リスト (SCENARIO)
2. 初期状態 CharacterState (INITIAL_STATE)
3. バリデーション関数 validate_scenario()

## 受け入れ条件
- [x] 7日分のイベントが定義されている
- [x] 初期状態が定義されている
- [x] バリデーション関数が実装されている
- [ ] pytest tests/test_scenario.py -v が全件 Pass
- [ ] mypy, ruff がエラー 0

## 影響範囲
- csdg/scenario.py (新規)
- tests/test_scenario.py (新規)
