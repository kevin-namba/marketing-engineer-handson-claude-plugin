# LP の HTML の骨組み

外部のライブラリに頼らない最小の形。計測タグと JavaScript は lp-measurement-tags の `references/tag-snippets.md` から入れる。

- 差し替える箇所は `<!-- lp:名前 -->…<!-- /lp:名前 -->` で囲む。計測する区画には `data-section="<区画の名前>"` を付ける（名前は LP をまたいで固定する）
- 画像は `width` / `height` を明示し、ファーストビュー以外は `loading="lazy"`。外部のフォントや大きな画像を積まない
- 意味の切れ目を保ちたい句だけ折り返しを禁じる。ただし 8 文字程度まで（長い句に付けると、スマホの幅で右側が切れる）

```html
<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>昼休みの 60 分で、カットまで終わる｜◯◯美容室</title>
<meta name="description" content="…">
<meta property="og:title" content="…">
<meta property="og:description" content="…">
<meta property="og:image" content="assets/ogp.png">
<!-- TODO: 計測未設定（GTM / GA4 / Meta の ID を受け取ったら lp-measurement-tags の手順で入れる） -->
<style>
  body { margin: 0; font-family: system-ui, sans-serif; line-height: 1.7; padding-bottom: 72px; }
  .sticky-cta { position: fixed; left: 0; right: 0; bottom: 0; padding: 12px 16px; background: #fff; }
  .btn { display: block; text-align: center; padding: 14px; border-radius: 8px; background: #F5A623; color: #fff; font-weight: 700; text-decoration: none; }
</style>
</head>
<body>
<header data-section="fv">
  <h1><!-- lp:headline -->昼休みの 60 分で、カットまで終わる<!-- /lp:headline --></h1>
  <p><!-- lp:subcopy -->駅から徒歩 3 分。平日 11〜16 時は待ち時間なし<!-- /lp:subcopy --></p>
  <!-- lp:kv --><img src="assets/kv.jpg" alt="店内の様子" width="1080" height="720" loading="eager"><!-- /lp:kv -->
  <a class="btn" href="#form" data-cv="cta_click" data-position="fv"><!-- lp:cta -->空き枠を見る<!-- /lp:cta --></a>
</header>
<section data-section="fv_below">…裏付け…</section>
<section data-section="price">…料金…</section>
<section data-section="voice">…お客様の声（実在の声だけ）…</section>
<section data-section="faq">…よくある質問…</section>
<section data-section="cta_bottom" id="form">
  <p><!-- lp:offer -->初回のカット＋カラーが 30% オフ（平日 11〜16 時の来店のみ）<!-- /lp:offer --></p>
  <form action="#" method="post" data-cv-form="reserve_complete"><!-- TODO: 送信先未確定 -->
    <input type="hidden" name="utm_source"><input type="hidden" name="utm_medium">
    <input type="hidden" name="utm_campaign"><input type="hidden" name="utm_content">
    <input type="hidden" name="gclid"><input type="hidden" name="fbclid">
    <input type="hidden" name="lp_variant">
    <label>お名前 <input name="name" required></label>
    <label>電話番号 <input name="tel" type="tel" required></label>
    <button class="btn" type="submit">予約する</button>
  </form>
</section>
<div class="sticky-cta"><a class="btn" href="#form" data-cv="cta_click" data-position="sticky">空き枠を見る</a></div>
<script>
  // VARIANT・trackCv・隠し項目への引き継ぎ・イベントの送信を、ここに入れる
  // （lp-measurement-tags の references/tag-snippets.md の「共通」と、入れ方 A / B / C の trackCv）
</script>
</body>
</html>
```
