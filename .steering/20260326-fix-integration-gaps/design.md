# 設計: 統合ギャップ修正

## 実装アプローチ
既存の実装済み機能を正しく配線する最小限の修正。新機能追加ではなく、デッドコードの活性化。

## 変更対象ファイル
| ファイル | 変更内容 |
|---|---|
| csdg/engine/pipeline.py | llm_client パラメータ追加、memory.update_after_day() への受け渡し、get_context_for_actor() 呼出、critic_log プロパティ追加 |
| csdg/engine/actor.py | update_state/generate_diary に long_term_context パラメータ追加、_format_long_term_context() メソッド追加 |
| csdg/main.py | PipelineRunner に llm_client を渡す、CriticLog.save() 呼出追加 |
| tests/test_pipeline.py | side_effect 関数のシグネチャ追従、統合ギャップテスト4件追加 |

## 代替案と選定理由
- 方式A (pipeline側でrevision_instructionに追記) → Phase 1に注入不可のため却下
- 方式B (Actor/Criticにパラメータ追加) → Phase 1/2 両方に注入可能、採用
