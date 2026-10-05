# 多言語ページの点検

> `seo-technical` の SKILL.md「多言語ページの点検」の節から読む。規則の出典は Google のドキュメント
> （https://developers.google.com/search/docs/specialty/international/localized-versions ）。

## 対応表

主要なテンプレートごとに 1 組（トップ・一覧・詳細・予約や問い合わせ）を選び、各言語版と、hreflang で指されている別言語版をすべて取得して作る。
取得できなかった言語版は「確認できない」。指定があるとみなさない。

```markdown
| URL | html lang | canonical | hreflang（コード → URL） | 自分自身 | 相手からの指定 | x-default |
```

hreflang の置き場所は 3 通り（HTML の `<link>` / HTTP ヘッダー / XML サイトマップ）。どれを使っているかを最初に確かめ、1 つに決める。

## 誤りと直し方

| 誤り | 重大度 | 直し方 |
|---|---|---|
| 自分自身への指定が無い | 重大 | 自分の URL を指す行を足す |
| 相互の指定が無い（A → B だけ） | 重大 | 相手の側にも行を足す |
| 言語コードが誤り（`jp` → `ja`、`eng` → `en`、`cn` → `zh`、`kr` → `ko`） | 高 | ISO 639-1 に直す |
| 地域コードが誤り（`en-UK` → `en-GB`） | 高 | ISO 3166-1 Alpha 2 に直す |
| 正規でない URL に hreflang を書いている | 高 | 正規の URL にだけ書く |
| x-default が無い | 中 | 言語の選択ページなどを指す行を足す |
| http と https が混ざっている / 末尾のスラッシュが canonical と違う | 中 | canonical の表記にそろえる |

あわせて、title と meta description がその言語で書かれているか、`<html lang>` が本文の言語と合っているかを見る。
翻訳の質は判定しない。

## 直したコード

```html
<!-- 日本語版 https://example.jp/plan/family/ の head -->
<link rel="canonical" href="https://example.jp/plan/family/">
<link rel="alternate" hreflang="ja" href="https://example.jp/plan/family/">
<link rel="alternate" hreflang="en" href="https://example.jp/en/plan/family/">
<link rel="alternate" hreflang="x-default" href="https://example.jp/language/">
```

ほかの言語版にも同じ alternate の行を並べ、canonical だけをそれぞれ自分の URL にする。
サイトへの反映はしない。生成したコードを渡すところまで。
