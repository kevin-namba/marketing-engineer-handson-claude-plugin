# 入力の列と設定

`scripts/pipeline_flags.py` と `scripts/weighted_forecast.py` が読む CSV の仕様。pipeline-review（週次のレビューと売上予測）と daily-briefing で同じ案件表を使う。

## 列

見出しは英語名でも日本語の別名でもよい。文字コードは UTF-8。

| 英語名 | 日本語の別名 | 無いとき |
|---|---|---|
| name（必須） | 案件名 / 企業名 / 会社名 / 商談名 | エラー |
| status（必須） | ステータス / ステージ | エラー |
| amount | 金額 / 月額 | 規模は 0 として並べ、形状では「金額が空」に入れる |
| term_months | 契約期間 / 期間 | 売上予測だけが使う |
| target_month | 成約予定 / 獲得目標月 | 期日超過は判定せず「未設定」 |
| owner | 担当者 | 衛生の対象から外す |
| next_action | 次アクション / ネクストアクション | 衛生の対象から外す |
| channel | チャネル / 流入元 | 衛生の対象から外す |
| updated_at | 最終更新日 / 最終活動日 | 停滞は「未取得」 |
| stage_entered_at | ステータス変更日 / ステージ変更日 | 行き詰まりは「未取得」 |
| contacts | 連絡先の数 / 相手側の連絡先の数 | 単線は「未取得」 |
| postponed_count | 先送り回数 | 先送りでは判定しない |
| last_response_at | 最終反応日 | 最終更新日で代用する |

- 日付は `YYYY-MM-DD`（`YYYY/MM/DD` も読む）。成約予定は `YYYY-MM` まで読む
- 金額は数字以外の文字（¥・カンマ・「円」）を取り除いて読む。「30万」のような略記は読めないので、数字に直してから渡す
- 列そのものが無い場合は「未取得」、列はあるがその案件だけ空の場合は「衛生」のフラグになる
- 売上予測は任意で commit / コミット列（yes・no）も読む

## 設定の変え方

`thresholds.json` を写して直し、`--thresholds` で指定する。

| キー | 意味 |
|---|---|
| idle_days / stuck_days | 停滞・行き詰まりの日数 |
| single_thread_contacts | この人数以下を単線とする |
| prune_silent_days / prune_postponed_count | 削除候補の条件 |
| focus_count | 今週注力する件数 |
| weights | 優先順位の重み（合計 100 にする） |
| closed_statuses / status_order | ステータス表（`--statuses`）を渡さないときの代用（対象から外すステータスと、ステージの順） |
| size_bands | 規模別の区分。金額の大きい順に `{"label": "大型", "min": 400000}` の形で並べる |
