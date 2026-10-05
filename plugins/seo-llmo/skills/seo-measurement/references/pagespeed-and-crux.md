# 表示速度の計測

> `seo-measurement` の SKILL.md「表示速度の計測」の節から読む。API の仕様は執筆時点のもの。実装の前に公式ドキュメント
> （https://developers.google.com/speed/docs/insights/v5/get-started ・ https://developer.chrome.com/docs/crux/history-api ）で確かめる。

## 取得経路（上から順に試す）

1. 速度計測の MCP ツール（つないである場合）
2. 公式 API を直接呼ぶ（ラボは PageSpeed Insights API、実利用者は CrUX API）
3. 利用者が PageSpeed Insights の画面（pagespeed.web.dev）で測った結果を貼る
4. どれも無ければ「未取得」と、API キーの用意のしかた（Google Cloud で API キーを作り、Chrome UX Report API を有効にする）を書く

- API キーは環境変数 `GOOGLE_API_KEY` から読む。会話・引数・ファイル・成果物に書かない
- モバイルを既定にする。複数ページを測るときは、主要なテンプレートを 1 つずつ
- ページ単位の値が無くてサイト全体（オリジン）の値を使うときは、サイト全体の値だと明記し、別の欄に置く
- INP は実利用者の値にしか無い。ラボの Total Blocking Time を INP として書かない

## 判定（実利用者の 75 パーセンタイル）

| 指標 | 良好 | 要改善 | 不良 |
|---|---|---|---|
| LCP | 2.5 秒以下 | 2.5〜4.0 秒 | 4.0 秒超 |
| INP | 200 ms 以下 | 200〜500 ms | 500 ms 超 |
| CLS | 0.1 以下 | 0.1〜0.25 | 0.25 超 |

3 指標がそろっていて全部が良好なら合格、1 つでも良好でなければ不合格、そろっていなければ「未取得」。
ラボの値だけを根拠に「不合格」と書かない。

## PageSpeed Insights API（ラボ）

`GET https://www.googleapis.com/pagespeedonline/v5/runPagespeed`

- `url`（必須）/ `strategy`（`MOBILE` が既定・`DESKTOP`）/ `category`（`PERFORMANCE` など）/ `key`（任意。無いと回数制限にすぐ当たる）
- 控える値: パフォーマンスの点数（`lighthouseResult.categories.performance.score` × 100）と、
  `audits` の `largest-contentful-paint`・`total-blocking-time`・`cumulative-layout-shift` の `numericValue`

## CrUX API（実利用者。直近 28 日）

`POST https://chromeuxreport.googleapis.com/v1/records:queryRecord`

- API キーは URL ではなく、ヘッダー `X-Goog-Api-Key` で送る（キーは必須）
- `url`（ページ単位）か `origin`（サイト全体）のどちらか一方 / `formFactor`（`PHONE`・`DESKTOP`・`TABLET`）
- 指標の名前: `largest_contentful_paint` / `interaction_to_next_paint` / `cumulative_layout_shift`
- **CLS の p75 は文字列**で返る。数値に直してから比べる。LCP・INP は ms の整数

```json
{ "record": {
    "metrics": { "largest_contentful_paint": { "percentiles": { "p75": 2100 } }, "cumulative_layout_shift": { "percentiles": { "p75": "0.05" } } },
    "collectionPeriod": { "firstDate": { "year": 2026, "month": 9, "day": 3 }, "lastDate": { "year": 2026, "month": 9, "day": 30 } } } }
```

- 404 はデータが無いという意味（認証の誤りではない）。`origin` で取り直し、それも無ければ「未取得（訪問が少ないサイトでは正常）」

## CrUX History API（週ごとの推移）

`POST https://chromeuxreport.googleapis.com/v1/records:queryHistoryRecord`

- リクエストは CrUX API と同じ形。`collectionPeriodCount` で週数を指定する（既定 25・最大 40）。値は `percentilesTimeseries.p75s` の配列で返る
- 値のある最初の週と最後の週を比べる。変化が 5% 以上なら「改善」か「悪化」、5% 未満なら「横ばい」
- 各点はその週で終わる 28 日間の集計。改修の効果は、改修日から 28 日以上あけた点と比べる
- 値の無い週（`null`）は計算の前に除く。0 として扱わない
