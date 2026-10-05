# ルールと実績のファイルの書式

`scripts/judge.py` が読む書式。媒体の制約は執筆時点のもの。使う前に公式ドキュメントで確かめる。

## ルール（`rules.json`）

`{"rules": [...]}` の形で、条件（広告の実績か、曜日と時刻）と操作の組を 1 件ずつ書く。例は同梱の `rules.json`。

| 項目 | 必須 | 書くこと |
|---|---|---|
| `name` | 必須 | ルールの名前。実行の記録の照合に使うので、重複させない |
| `enabled` | 任意 | false なら判定しない（既定は true） |
| `media` | 必須 | `Meta` / `Google` / `TikTok` / `LINEヤフー` |
| `condition.kind` | 必須 | `広告の実績` か `曜日と時刻` |
| `condition.metric` / `comparison` / `threshold` | 実績の条件で必須 | 指標は `CPA` / `CTR`（パーセント）/ `CPC` / `CPM` / `消化額` / `成果の件数`。比較は `より大きい` / `より小さい`。閾値の金額は通貨の額 |
| `condition.days` / `condition.hour` | 時刻の条件で必須 | 曜日（`月`〜`日` の配列）と時（0〜23） |
| `window_days` | 実績の条件で必須 | 集計期間の日数。実績のファイルの行と同じ日数であること |
| `min_spend` | 実績の条件で必須 | 最低消化額。これ未満の対象は判定しない。**0 にできない** |
| `min_conversions` / `max_conversions` | 任意 | 成果がこの件数に届かない対象は見送る / この件数以下の対象だけに当てはめる |
| `target.level` | 必須 | `キャンペーン` / `広告セット`（Meta）/ `広告グループ`（Meta 以外）/ `広告` |
| `target.ids` | 必須 | 対象の ID の配列。空なら、その階層のすべて。**支出が増える操作と時刻の条件では、空にできない** |
| `action` | 必須 | `通知する` / `停止する` / `日予算を減らす` / `日予算を増やす` / `複製する` / `配信を開始する` |
| `step_percent` | 予算の操作で必須 | 1 回に動かす割合（%） |
| `budget_min` / `budget_max` | 予算の操作で必須 | 予算の下限と上限（通貨の額）。**両方とも書く** |
| `cooldown_minutes` | 必須 | 同じ対象に同じ操作を次に行えるまでの待ち時間（分） |
| `max_per_day` | 必須 | このルールが 1 日に実行してよい回数 |
| `notify` | 必須 | 通知先 |
| `approved` | 支出が増える操作で要る | `{"by": "承認した人", "on": "YYYY-MM-DD"}`。無ければ「提案する」に入る |

- 成果 0 件の CPA は計算できないので、「CPA がいくらより大きい」の条件には当てはまらない。撤退ラインで止めるときは、
  `消化額` の条件と `max_conversions: 0` で書く。
- 増額は、20% 増やすと上限を超える回は実行せずに提案になる。学習期間中（`learning: true`）の対象は増額しない。
- 時刻の条件で書ける操作は、配信の開始と停止だけ。巡回が動いた時刻の「時」が一致したときに当てはまる。

```json
{"name": "平日の 9 時に平日限定プランの配信を始める", "media": "Meta",
 "condition": {"kind": "曜日と時刻", "days": ["月", "火", "水", "木", "金"], "hour": 9},
 "target": {"level": "広告セット", "ids": ["（承認した広告セットの ID）"]},
 "action": "配信を開始する", "cooldown_minutes": 720, "max_per_day": 1,
 "notify": "広告の通知チャンネル", "approved": {"by": "（承認した人）", "on": "2026-10-01"}}
```

読み込んだ時点でエラーになるもの:

- 複製は Meta のキャンペーンだけ（Google と LINEヤフーには複製の API が無い。TikTok は対象にしない）
- 日予算を動かせる階層は、Meta はキャンペーンか広告セット、Google・LINEヤフー・TikTok はキャンペーンだけ
- 最低消化額が 0、予算の下限・上限の片方だけ、支出が増える操作で対象が空、配信の開始を実績の条件で書く

## 実績のファイル（`metrics.json`）

```json
{
  "fetched_at": "2026-10-05T09:00:00+09:00",
  "media": {
    "Meta": {
      "status": "ok", "currency": "JPY", "units": {"spend": "major", "daily_budget": "minor"},
      "rows": [
        {"level": "広告セット", "id": "（広告セットの ID）", "name": "髪質改善_20-39歳", "window_days": 7,
         "spend": 12000, "impressions": 48000, "clicks": 520, "conversions": 6,
         "daily_budget": 2000, "delivery": "配信中", "learning": false}
      ]
    },
    "Google": {"status": "未取得", "reason": "認証エラー（再連携が必要）"}
  }
}
```

- `status`: `ok` か `未取得`。未取得の媒体は判定されない。
- `units.spend` / `units.daily_budget`: `major`（通貨の額）/ `minor`（通貨の最小単位）/ `micros`（100 万分の 1）。省略すると `major`。
  目安は、Meta が `spend` = `major`・`daily_budget` = `minor`、Google がどちらも `micros`、TikTok と LINEヤフーがどちらも `major`。
- `rows[].window_days` がルールの `window_days` と一致する行だけが判定される。
- `spend` / `impressions` / `clicks` / `conversions` は期間の合計。**取れなかった項目は `null`**。率は書かない（スクリプトが計算する）。
- `daily_budget` は予算の操作のルールで要る。`delivery`（`配信中` / `停止中`）と `learning` は、分からなければ省略する。
- `minor` を通貨の額に直す数はスクリプトの中の表（円 = 1、ドル = 100）で決まる。表に無い通貨では、金額を使うルールを判定しない。

## スクリプトの結果と実行の記録

```json
{"status": "ok",
 "実行する": [{"rule": "…", "media": "Meta", "level": "広告セット", "id": "…", "name": "…", "action": "停止する",
              "reason": "直近 7 日の CPA 10000 が 8000 より大きい（消化額 20000、成果 2 件）",
              "args": {"status": "PAUSED"}, "notify": "広告の通知チャンネル"}],
 "提案する": [], "見送る": [],
 "summary": {"実行する": 1, "提案する": 0, "見送る": 0, "条件に当てはまらなかった件数": 4}}
```

- `args.status` には媒体ごとの語が入る。予算の操作の `args` は `from` / `to`（通貨の額）と `to_in_media_unit`（ツールにはこちらを渡す）。
- エラーのときは `{"status": "error", "errors": [...]}` と終了コード 1。何も実行しない。実行の記録が読めないときもエラーになる。
- 実行の記録（`patrol-log.jsonl`）は 1 行 1 件で、`judge.py record` で追記する。待ち時間と 1 日の上限回数に数えるのは、
  `result` が「実行した」の行だけ。
