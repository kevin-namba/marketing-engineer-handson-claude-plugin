# 構造化データ

> `seo-technical` の SKILL.md「構造化データ」の節から読む。型の扱いと必須項目は執筆時点の内容。提案の前に Google 検索セントラルの検索ギャラリーで確かめる。

## いまある構造化データの点検

`<script type="application/ld+json">` の中身をすべて取り出して確かめる。所見は、誤り → 要確認 → 注意 → 情報 の順に並べる。

| 確かめること | 判定 |
|---|---|
| JSON として読めるか / `@context` / `@type` | 読めない・schema.org でない・`@type` が無いものは誤り |
| 必須項目 | Product は `name` と、`offers`・`review`・`aggregateRating` のどれか。LocalBusiness は `name` と `address`。BreadcrumbList は `itemListElement` |
| 置き換え忘れ | `[Company Name]` のような値、「要確認」「TODO」が残っていれば誤り |
| URL・日付・`price` | 相対 URL は誤り / 日付は ISO 8601（`2026-10-04`）/ `price` は数値だけ（`¥2,980` は誤り） |
| 表示との一致 | `name`・`price`・`telephone`・`ratingValue`・`streetAddress` などがページの表示に見当たらなければ「要確認」 |

公開前に、リッチリザルト テスト（https://search.google.com/test/rich-results ）か Schema.org の検証ツール（https://validator.schema.org/ ）に通す。

## 型の選び方

| 型 | 使いどころ | 主な項目 |
|---|---|---|
| `Organization` | 会社・団体のトップ、会社概要 | name, url, logo, contactPoint, sameAs（`@id` を付け、ほかの型から参照する） |
| `LocalBusiness` の下位の型 | 店舗・拠点（`Restaurant`・`Hotel`・`HairSalon`・`Dentist` など） | name, address, telephone, openingHours, geo, priceRange |
| `Article` / `BlogPosting` | 記事 | headline, author, datePublished, dateModified, image, publisher |
| `Product` | 商品 | name, image, description, sku, brand, offers |
| `Service` | サービス | name, provider, areaServed, description, offers |
| `BreadcrumbList` | パンくず | itemListElement（表示されているパンくずと同じ並び・同じ名前） |

形式は JSON-LD。価格や在庫のように頻繁に変わる値（Product・Offer）は、最初の HTML に入れる。

## 装飾表示（リッチリザルト）が終わった型

表示目的で足さない。既存の記述を急いで消す提案もしない。

| 型 | 状況 | 代わり |
|---|---|---|
| HowTo | 2023 年に装飾表示が終了 | 手順は、見出しのある本文で書く |
| FAQPage | 2026 年 5 月に装飾表示が終了 | 利用者が質問し利用者が答えるページなら QAPage |
| SpecialAnnouncement | 2025 年 7 月に終了 | 期間が決まっていれば Event、そうでなければ Article |

## 雛形

店舗（型は業種に合うものに変える。複数拠点は拠点ごとに 1 つ作り、`@id` を分ける）:

```json
{
  "@context": "https://schema.org", "@type": "Restaurant", "@id": "https://example.jp/shop/ekimae/#shop",
  "name": "要確認（店名。看板・他の掲載先と同じ表記）", "url": "https://example.jp/shop/ekimae/", "telephone": "要確認",
  "address": { "@type": "PostalAddress", "postalCode": "要確認", "addressRegion": "要確認", "addressLocality": "要確認", "streetAddress": "要確認", "addressCountry": "JP" },
  "openingHoursSpecification": [{ "@type": "OpeningHoursSpecification", "dayOfWeek": ["Monday", "Tuesday"], "opens": "要確認（11:00 の形）", "closes": "要確認" }]
}
```

商品（`availability` はいまの表示に合わせる。レビューと評点は、ページに表示されているときだけ足す）:

```json
{
  "@context": "https://schema.org", "@type": "Product",
  "name": "要確認", "image": ["要確認（絶対 URL）"], "description": "要確認", "sku": "要確認",
  "brand": { "@type": "Brand", "name": "要確認" },
  "offers": { "@type": "Offer", "url": "要確認", "priceCurrency": "JPY", "price": "要確認（数値だけ）", "availability": "https://schema.org/InStock" }
}
```

表示に無い項目は、雛形から行ごと消す。「要確認」が残っているコードは、公開してはいけないものとして渡し、残っている項目を一覧にして添える。
