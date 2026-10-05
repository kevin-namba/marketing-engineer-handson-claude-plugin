# 検索実績の取得

> `seo-measurement` の SKILL.md「検索実績の取得」の節から読む。API の仕様は執筆時点のもの。実装の前に https://developers.google.com/webmaster-tools で確かめる。

## 取得経路（上から順に試す。取った経路を成果物に書く）

| 順 | 経路 | 注意 |
|---|---|---|
| 1 | Search Console の MCP ツール（つないである場合） | 使えるなら、他の経路は使わない |
| 2 | 公式 API / 公式の CLI で**利用者が**出した結果（JSON・CSV） | 認証情報（トークンなど）を会話や成果物に貼らせない |
| 3 | 管理画面（検索パフォーマンス → エクスポート）の CSV | 1 つの軸・最大 1,000 行。**CTR は % の文字列**（そう明記して渡す） |
| 4 | 利用者が貼った数字 | どの期間・どの画面の値かを一緒に聞く |
| — | どれも無い | 「未取得」と理由、何をすれば取れるかを書いて終える |

- ドメインプロパティ（`sc-domain:example.com`）と URL プレフィックス（`https://example.com/`、末尾のスラッシュが必須）は**別のプロパティ**
- 既定: 終了日は **3 日前** / 直近 28 日 / 上限はクエリ 200・ページ 200・クエリ×ページ 500（上限で切ったことを書く）/ `final`（確定値）
- 流入の分析に渡すときは 4 回取る: 全体合計（軸なし）/ クエリ別 / ページ別 / クエリ×ページ。期間比較は呼び出しを分ける
- 渡すときに添える: プロパティ / 期間 / 軸 / 行数 / **ctr は 0〜1** / 取得経路 / 取得日

## 検索パフォーマンス

`POST https://www.googleapis.com/webmasters/v3/sites/{siteUrl}/searchAnalytics/query`（`{siteUrl}` は URL エンコードして入れる）

```json
{ "startDate": "2026-07-11", "endDate": "2026-08-07", "dimensions": ["query", "page"], "rowLimit": 500, "dataState": "final" }
```

```json
{ "rows": [ { "keys": ["温泉旅館 子連れ", "https://example.com/plan/family/"], "clicks": 150, "impressions": 5000, "ctr": 0.03, "position": 4.2 } ] }
```

- `dimensions`: `query` / `page` / `country` / `device` / `date`。空にすると全体の合計が 1 行で返る
- `rowLimit`: 1〜25000（既定 1000）。`dataState`: `final`（既定）/ `all`（未確定を含む）
- `position` は表示されたときの順位の平均。狙った語の順位としては使えない

## URL 検査

`POST https://searchconsole.googleapis.com/v1/urlInspection/index:inspect`

```json
{ "inspectionUrl": "https://example.com/blog/post-1", "siteUrl": "sc-domain:example.com", "languageCode": "ja" }
```

- `indexStatusResult` で読む項目: `verdict` / `coverageState` / `robotsTxtState` / `indexingState` / `pageFetchState` / `googleCanonical` / `userCanonical` / `lastCrawlTime`
- **Google が選んだ正規 URL**（`googleCanonical`）と**ページが宣言した正規 URL**（`userCanonical`）が違えば、そのまま報告する
- 上限はプロパティごとに 1 日 2,000 件（執筆時点）。対象を絞ってから検査する

## サイトマップとプロパティの一覧

| メソッドと URL | 内容 |
|---|---|
| `GET https://www.googleapis.com/webmasters/v3/sites` | プロパティの一覧（`siteUrl` と `permissionLevel`） |
| `GET https://www.googleapis.com/webmasters/v3/sites/{siteUrl}/sitemaps` | サイトマップの一覧。示すのは送信した件数 |
| `PUT` / `DELETE` `…/sitemaps/{feedpath}` | 送信 / 削除。**外部反映。この Skill では呼ばない** |

送信と送信後の確認は `seo-technical` の「サイトマップ」の節（`references/sitemap-submit.md`）で行う。

## 取れないときの切り分け

| 症状 | 原因 | 対処 |
|---|---|---|
| 連携は通るのに取得だけ 403 | そのアカウントに、プロパティの権限が無い | Search Console の「ユーザーと権限」でユーザーに追加する |
| Search Console だけ 403 | ドメインプロパティと URL プレフィックスを取り違えている | プロパティを一覧から選び直す |
| 翌週になって 401（invalid_grant） | 同意画面がテスト状態でトークンが 7 日で失効した | 同意画面を本番に公開し、連携し直す |
| 連携したのに数字が「—」 | 見るプロパティを選んでいない | 一覧から選ぶ |
