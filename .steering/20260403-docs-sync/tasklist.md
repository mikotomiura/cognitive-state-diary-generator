# タスクリスト: ドキュメント・コード整合性同期

## 実装タスク
- [x] glossary.md: EMOTION_SENSITIVITY.stress -0.3→-0.45、Day4 impact -0.9→-0.8
- [x] architecture.md: decay_rate 0.1→0.15、event_weight 0.6→0.75、stress -0.3→-0.45、LLM設定をプロバイダー分離構造に更新
- [x] functional-design.md: stress sensitivity -0.3→-0.45、Temperature Decay を区分線形に修正
- [x] repository-structure.md: prompt_loader.py追加、test_llm_client.py追加、llm_client.py説明をGemini対応に更新
- [x] development-guidelines.md: expected_delta算出例を新感度係数に更新、Temperature Decay を区分線形に修正
- [x] .env.example: CSDG_EMOTION_SENSITIVITY_STRESS -0.3→-0.45
- [x] schemas.py: CriticResult weights デフォルト値 0.3/0.2/0.5→0.40/0.35/0.25

## テストタスク
- [x] pytest tests/ -v 全505テスト Pass
