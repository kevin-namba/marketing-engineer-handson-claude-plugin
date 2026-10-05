---
name: lp-measurement-tags
description: >-
  LP に GA4・Meta ピクセル・Google タグマネージャー（GTM）の計測タグを入れ、
  申し込みボタンを押してデータが送られるかまで確かめる。
  「LP に計測タグを入れて」「GA4 のタグを埋め込んで」「タグが動いているか確かめて」で使う。
  ※LP を作るところからは landing-page-builder、既存ページの改善は lp-improve。
---

# LP に計測タグを入れる

「入っている」と「送っている」は別なので、タグを入れたあと、ボタンを押してデータが送られることまで確かめる。

## 最初に確定すること

- 入力: LP の HTML ファイル、計測 ID（GTM のコンテナ ID `GTM-XXXXXXX` / GA4 の測定 ID `G-XXXXXXXXXX` / Meta のピクセル ID）、
  最終 CV の種類（予約完了・フォーム送信・LINE の友だち追加ボタン・電話番号のタップ）
- 扱うのは手元の HTML ファイル。管理画面（GA4・GTM・Meta）の設定や公開中のサイトへの反映は人が行う（必要な設定を一覧にして渡す）

## 入れ方（手元の ID で選ぶ。コードは `references/tag-snippets.md`）

- GTM のコンテナ ID がある（推奨）: GTM のコンテナだけを埋め込み、GA4 と Meta ピクセルは GTM 側で管理する。
  申し込みは `dataLayer.push({event: 'cv', cv_name: 名前})` で送る
- GA4 の測定 ID や Meta のピクセル ID だけがある: gtag.js と fbq を直接貼る。
  申し込みで `gtag('event', 'generate_lead')` と `fbq('track', 'Lead')` を送る
- どちらも無い: ダミーの ID は入れない。`<!-- TODO: 計測未設定 -->` を残し、
  納品書類の冒頭に「計測未設定。このまま配信すると成果が計測できない」と書く

## 必ず入れるもの

- 申し込みの送信は 1 つの関数（`trackCv`）にまとめ、タグはそこからだけ呼ぶ。各 CTA には `data-cv="<イベント名>"` を付ける
- URL の `utm_*`・`gclid`・`fbclid` を読み取り、フォームの隠し項目に入れる
- 計測イベントには LP の案の ID を付ける（`variant`）
- LP の中の動きを計測するイベント。名前は LP をまたいで固定する

| イベント | いつ送るか | パラメータ |
|---|---|---|
| `section_view` | 区画が画面に入ったとき（1 訪問につき区画ごとに 1 回） | `section`（`fv_below` / `price` / `voice` / `faq` / `cta_bottom` など）、`variant` |
| `cta_click` | CTA を押したとき | `position`（`fv` / `mid` / `bottom` / `sticky`）、`variant` |
| `form_start` | フォームに最初に触れたとき | `variant` |
| 最終 CV（`reserve_complete` など） | 予約完了・フォーム送信など | `variant` |

## 手順

1. 与件から計測 ID を確認する。GA4 の測定 ID（`G-` で始まる）とプロパティ ID（数字だけ）を取り違えない。
   すでにタグが入っている LP は、先に静的チェックで今の状態を読む。ID が「無い・分からない」ときは「どちらも無い」の扱いで進める
2. 上の 3 通りから入れ方を選び、埋め込む
3. 静的チェック: タグ・申し込みの関数・隠し項目がそろっているかを確かめる（依存なし）
4. 実発火チェック: ブラウザで LP を開いて申し込みボタンを押し、GA4・GTM・Meta へのリクエストが実際に送られるかを確かめる
   （Playwright が必要。無いと実発火チェックは行われず、その旨が結果の `notes` に入る）
5. 人が管理画面で行う設定を一覧にして渡す: パラメータ（`section` / `position` / `variant`）の「カスタム ディメンション」への登録、
   最終 CV の「キーイベント」への登録、GTM のタグ・トリガー・変数。登録した日より前のデータは後から取れない

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/lp-measurement-tags/scripts/verify_tags.py" --path lp/a/index.html --json
python3 "${CLAUDE_PLUGIN_ROOT}/skills/lp-measurement-tags/scripts/verify_tags.py" --path lp/a/index.html --live --json
```

結果の `status` を項目ごとに読む: `ok` = 問題なし / `warn` = 改善余地 / `missing` = 欠落 / `todo` = 意図的な未設定。
`missing` が残るあいだは `ready_to_run_ads` が false になる。`--json` では失敗しても終了コード 0 なので、必ず `error` を読む。
実発火チェックで押すと計測サービスにテストのデータが送られる。公開前の LP で行う。

## 守ること

- ダミーの ID を入れない。プレースホルダ（`GTM-XXXXXXX` など）のまま「設定済み」と書かない
- 同じタグを二重に入れない（GTM の中で GA4 を管理しているのに、gtag も直接貼ると二重に数える）
- 実発火チェックをしていないのに「発火を確認した」と書かない。静的チェックだけなら「実発火は未確認」と書く
- LP の計測イベントの数と、媒体が報告する CV の数は数え方が違う。突き合わせず、足さない
- API のシークレットは LP に書かない

## 出力の型

- 計測の状態（入れたタグ / 未設定のタグ / 送る経路）と、人が管理画面で行う設定の一覧
- 検証の各項目（計測の経路・CTA の data-cv・trackCv への集約・広告のパラメータの引き継ぎ・フォームの送信先・実発火）を
  「問題なし／改善余地／欠落／意図的な未設定」で書く。欠落が残るあいだは「配信できる」と書かない

## フォールバック先

- ブラウザが使えない: 静的チェックだけを行い、結果に「実発火は未確認」と書く。人が開発者ツールの「ネットワーク」で
  `collect`（GA4）・`gtm.js`（GTM）・`tr`（Meta）へのリクエストを確かめる手順を添える
- ID が無い: 「どちらも無い」の扱いにし、ID の発行手順を添えて返す（画面の名前は変わるので、公式のヘルプで確認する）
- Python を実行できない: HTML を読んで、`references/tag-snippets.md` の「確かめる項目」を 1 つずつ目で確かめる
- LP が HTML ファイルではない（CMS・ノーコードのサービス）: 入れるコードと、入れたあとに確かめる項目を渡し、設置は人が行う
