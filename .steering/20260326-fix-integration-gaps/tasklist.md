# タスクリスト: 統合ギャップ修正

## 実装タスク
- [x] pipeline.py: llm_client パラメータ追加、memory.update_after_day() に受け渡し
- [x] pipeline.py: get_context_for_actor() 呼出、Actor に long_term_context を渡す
- [x] pipeline.py: critic_log プロパティ追加
- [x] actor.py: update_state/generate_diary に long_term_context パラメータ追加
- [x] actor.py: _format_long_term_context() メソッド追加
- [x] actor.py: _build_state_update_prompt/_build_generator_prompt にコンテキスト注入
- [x] main.py: PipelineRunner に client を渡す
- [x] main.py: CriticLog.save() 呼び出し追加

## テストタスク
- [x] test_pipeline.py: side_effect 関数のシグネチャ追従 (3箇所)
- [x] test_pipeline.py: 統合ギャップテスト4件追加
- [x] 全テスト Pass 確認 (294/294)
- [x] mypy --strict Pass 確認
- [x] ruff check Pass 確認

## ドキュメント更新
- [x] README.md: Task 4 は既に修正済みのため対応不要
- [x] repository-structure.md: critic_log.jsonl を追記
