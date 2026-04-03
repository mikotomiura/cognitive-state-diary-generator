# 要件定義: ドキュメント・コード整合性同期

## 背景
直近の品質チューニングコミット群 (温度スケジュール区分線形化、感度係数調整、Critic閾値最適化等) の結果がドキュメントに反映されておらず、コードとドキュメントに乖離が発生していた。

## 実装内容
ドキュメント全体をコードの現在値に同期する。

## 受け入れ条件
- [x] パラメータ値がコードと一致 (emotion_sensitivity_stress, decay_rate, event_weight)
- [x] ファイル一覧がコードと一致 (prompt_loader.py, test_llm_client.py)
- [x] schemas.py の CriticResult weights デフォルト値が config.py と整合
- [x] 全テスト Pass

## 影響範囲
- docs/glossary.md, architecture.md, functional-design.md, repository-structure.md, development-guidelines.md
- .env.example
- csdg/schemas.py
