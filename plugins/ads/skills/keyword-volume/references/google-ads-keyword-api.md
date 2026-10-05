# Google Ads API のキーワードプランナー（使う範囲だけ）

執筆時点の控え。API のバージョンはおおむね 1 年強で廃止されるので、実装前に公式のリリースノート
（https://developers.google.com/google-ads/api/docs/release-notes）で最新のバージョンとフィールド名を確かめる。

## 認証とエンドポイント

- ホスト: `https://googleads.googleapis.com`。ヘッダは `Authorization: Bearer <access_token>` と `developer-token`（必須）、
  MCC 経由のときだけ `login-customer-id`（ハイフン無し）。
- スコープは `https://www.googleapis.com/auth/adwords`。**読み取り専用のスコープは無い**ので、書き込みはパーミッションの設定で止める。
- サービスアカウントだけでは使えない。Google 広告の側で、連携するアカウントをユーザーとして招待する。

| 用途 | メソッド | パス |
|---|---|---|
| アクセスできるアカウントの一覧 | GET | `/{version}/customers:listAccessibleCustomers` |
| キーワードの候補 | POST | `/{version}/customers/{customer_id}:generateKeywordIdeas` |
| 指定したキーワードの過去の指標 | POST | `/{version}/customers/{customer_id}:generateKeywordHistoricalMetrics` |
| 地域 ID の検索 | POST | `/{version}/geoTargetConstants:suggest` |

顧客 ID は手入力させず、一覧から選ばせる。

## リクエスト（キーワードの候補）

- `language`: `languageConstants/{id}`（1005 = 日本語 / 1000 = 英語）
- `geoTargetConstants`: `geoTargetConstants/{id}` の配列。最大 10 件（2392 = 日本 / 2840 = 米国。都道府県・市区町村は公式の一覧で引く）
- `keywordPlanNetwork`: `GOOGLE_SEARCH` / `GOOGLE_SEARCH_AND_PARTNERS`（既定は後者）
- 元になる指定は `keywordSeed.keywords`（1〜20 件）/ `keywordAndUrlSeed` / `urlSeed.url` / `siteSeed.site` のいずれか 1 つだけ
- 過去の指標のメソッドは `keywords`（最大 10,000）を直接渡す。近い表記の語は 1 行にまとめられ、`closeVariants` に入る

## 返る指標

| JSON | 意味 |
|---|---|
| `avgMonthlySearches` | 直近 12 か月の月間平均。**未設定は「データ無し」**（0 ではない） |
| `monthlySearchVolumes[]` | `year` / `month`（`JANUARY` などの語。数値ではない）/ `monthlySearches` |
| `competition` | `LOW` / `MEDIUM` / `HIGH`。`UNSPECIFIED` / `UNKNOWN` は「データ不足」であって「競合が低い」ではない |
| `competitionIndex` | 0〜100。埋まった広告枠 ÷ 広告枠の総数。SEO の難易度ではない |
| `lowTopOfPageBidMicros` / `highTopOfPageBidMicros` | ページ上部の入札額の、下から 20% / 80% にあたる額 |

`*Micros` は必ず 1,000,000 で割る。int64 は JSON では文字列で返るので、数値に直してから計算する。

## よくあるエラー

| 症状 | 原因 | 直し方 |
|---|---|---|
| `DEVELOPER_TOKEN_NOT_APPROVED` | 開発者トークンが未承認 | アクセスレベルの申請をするか、テストアカウントで検証する |
| `USER_PERMISSION_DENIED` | 連携した Google アカウントが、その広告アカウントのユーザーでない | Google 広告の「管理者 → アクセスとセキュリティ」で招待する |
| `CUSTOMER_NOT_FOUND` | 顧客 ID の間違い | 一覧から選び直す |
| MCC の配下が見えない | `login-customer-id` が未設定 | MCC の ID をヘッダに入れる |
| 401 / `invalid_grant` | トークンの失効、または `adwords` スコープを付けずに連携した | 連携をやり直す |
