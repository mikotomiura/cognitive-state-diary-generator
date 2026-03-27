# 要件定義: advice.md 残存改善項目の実装

## 背景
MVP後改善タスク v2 (advice.md) のうち、タスク1のv2追加項目（max_llm_delta clipping、指数温度減衰）とタスク4（Criticログ蓄積と軽量フィードバック）が未実装。

## 実装内容
1. **max_llm_delta clipping**: LLM deltaの絶対値上限を設け、状態遷移の安定性を保証
2. **指数温度減衰**: 線形減衰から指数減衰に変更し、終盤の安定性を向上
3. **Criticログ蓄積**: CriticLogEntry/CriticLogクラスによるJSON Lines形式のログ保存
4. **軽量フィードバック**: 過去の低スコアパターンをActorプロンプトに注入

## 受け入れ条件
- [ ] max_llm_delta を超えるdeltaがclipされること
- [ ] clip後もllm_weightが正しく乗算されること
- [ ] 指数減衰が線形より終盤で低い値になること
- [ ] CriticLogEntryの保存/読み込み往復テスト
- [ ] get_low_score_patternsが頻度順ソート
- [ ] 空ログで空リスト返却
- [ ] 既存テスト184件全パス
- [ ] mypy strict / ruff クリーン

## 影響範囲
- `csdg/config.py` (設定追加)
- `csdg/engine/state_transition.py` (clipping追加)
- `csdg/engine/critic_log.py` (新設)
- `csdg/engine/pipeline.py` (ログ蓄積統合)
- `csdg/schemas.py` (CriticLogEntry追加の可能性)
- `tests/` (新規テスト追加)
- `docs/architecture.md`, `docs/repository-structure.md`
