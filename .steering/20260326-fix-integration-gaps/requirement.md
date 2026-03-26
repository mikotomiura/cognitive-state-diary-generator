# 要件定義: 統合ギャップ修正

## 背景
コードレビューで3件の統合ギャップが検出された。実装された機能が配線されておらず、デッドコードになっている。

## 実装内容
1. pipeline.py が llm_client を memory.update_after_day() に渡していない (P0)
2. get_context_for_actor/critic() が呼ばれず長期記憶がプロンプトに注入されない (P0)
3. CriticLog.save() が呼ばれずログが永続化されない (P1)

## 受け入れ条件
- [x] llm_client が memory.update_after_day() に渡される
- [x] get_context_for_actor() が Actor のプロンプトに注入される
- [x] CriticLog.save() が main.py から呼ばれる
- [x] 全テスト Pass (294/294)
- [x] mypy --strict Pass
- [x] ruff check Pass

## 影響範囲
- csdg/engine/pipeline.py
- csdg/engine/actor.py
- csdg/main.py
- tests/test_pipeline.py
