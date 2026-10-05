# 計測タグのコード

コードは執筆時点の形。実際に入れるときは、各サービスの管理画面が出すコードをそのまま使い、ID だけを差し替える。
ここに書いた `GTM-XXXXXXX` / `G-XXXXXXXXXX` / `YOUR_PIXEL_ID` は置き場所を示す印で、このまま LP に入れない
（検証のスクリプトは、これらを「意図的な未設定」として扱う）。

## A. GTM のコンテナ ID がある（推奨）

GTM のコンテナだけを埋め込み、GA4 と Meta ピクセルは GTM 側で管理する。

`<head>` のなるべく上:

```html
<!-- Google Tag Manager -->
<script>(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':
new Date().getTime(),event:'gtm.js'});var f=d.getElementsByTagName(s)[0],
j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src=
'https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);
})(window,document,'script','dataLayer','GTM-XXXXXXX');</script>
<!-- End Google Tag Manager -->
```

`<body>` の直後:

```html
<!-- Google Tag Manager (noscript) -->
<noscript><iframe src="https://www.googletagmanager.com/ns.html?id=GTM-XXXXXXX"
height="0" width="0" style="display:none;visibility:hidden"></iframe></noscript>
<!-- End Google Tag Manager (noscript) -->
```

`trackCv` の中身:

```js
function trackCv(name, params) {
  var p = Object.assign({ variant: VARIANT }, params || {});
  window.dataLayer = window.dataLayer || [];
  window.dataLayer.push(Object.assign({ event: 'cv', cv_name: name }, p));
}
```

GTM の管理画面で人が行う設定（一覧にして渡す）:

- 変数: データレイヤーの変数 `cv_name` / `section` / `position` / `variant`
- トリガー: カスタム イベント `cv`
- タグ: GA4 のイベント（イベント名に `cv_name`、パラメータに `section` / `position` / `variant`）、Meta ピクセル（最終 CV のときに `Lead` など）
- 公開の前に、GTM のプレビューで発火を確かめる

## B. GA4 の測定 ID や Meta のピクセル ID だけがある

gtag.js（`<head>` の中）:

```html
<script async src="https://www.googletagmanager.com/gtag/js?id=G-XXXXXXXXXX"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'G-XXXXXXXXXX');
</script>
```

Meta ピクセルの基本コード（`<head>` の中）:

```html
<script>
!function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){n.callMethod?
n.callMethod.apply(n,arguments):n.queue.push(arguments)};if(!f._fbq)f._fbq=n;
n.push=n;n.loaded=!0;n.version='2.0';n.queue=[];t=b.createElement(e);t.async=!0;
t.src=v;s=b.getElementsByTagName(e)[0];s.parentNode.insertBefore(t,s)}(window,
document,'script','https://connect.facebook.net/en_US/fbevents.js');
fbq('init', 'YOUR_PIXEL_ID');
fbq('track', 'PageView');
</script>
```

`trackCv` の中身（片方の ID しか無ければ、ある方だけを書く）:

```js
var FINAL_CV = ['reserve_complete'];   // 最終 CV のイベント名。LP ごとに決める

function trackCv(name, params) {
  var p = Object.assign({ variant: VARIANT }, params || {});
  if (typeof gtag === 'function') {
    gtag('event', name, p);                                   // section_view / cta_click / form_start / 最終 CV
    if (FINAL_CV.indexOf(name) !== -1) gtag('event', 'generate_lead', p);
  }
  if (typeof fbq === 'function' && FINAL_CV.indexOf(name) !== -1) {
    fbq('track', 'Lead');
  }
}
```

- Meta の標準イベントは、CV の種類に合うものを選ぶ（問い合わせ・予約なら `Lead`、購入なら `Purchase` など。公式のイベントの一覧で確認）
- 最終 CV の名前（`reserve_complete` など）は、GA4 の管理画面で「キーイベント」に登録する

## C. どちらも無い

`<head>` に `<!-- TODO: 計測未設定（GTM / GA4 / Meta の ID を受け取ったら入れる） -->` を残し、`trackCv` の中身も TODO のコメントだけにする。
ダミーの ID は入れない。`trackCv` と `data-cv`、隠し項目は入れておく（ID を受け取ったときに直す場所が 1 か所で済む）。

## 共通: 案の ID と広告のパラメータ

```js
// 案の ID。URL の ?lp= を優先し、無ければ埋め込みの値、どちらも無ければ a
var VARIANT = new URLSearchParams(location.search).get('lp') || window.LP_VARIANT || 'a';

// 広告のパラメータを、フォームの隠し項目に入れる
(function () {
  var q = new URLSearchParams(location.search);
  ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'gclid', 'fbclid'].forEach(function (k) {
    var v = q.get(k); if (!v) return;
    document.querySelectorAll('input[name="' + k + '"]').forEach(function (el) { el.value = v; });
  });
  document.querySelectorAll('input[name="lp_variant"]').forEach(function (el) { el.value = VARIANT; });
})();
```

```html
<input type="hidden" name="utm_source"><input type="hidden" name="utm_medium">
<input type="hidden" name="utm_campaign"><input type="hidden" name="utm_content"><input type="hidden" name="utm_term">
<input type="hidden" name="gclid"><input type="hidden" name="fbclid">
<input type="hidden" name="lp_variant">
```

フォームが別のページにあるとき（LP → 予約ページ）は、LP からのリンクにパラメータを引き継ぐ。

## 共通: イベントを送る場所

```js
// CTA のクリック
document.querySelectorAll('[data-cv]').forEach(function (el) {
  el.addEventListener('click', function () { trackCv(el.dataset.cv, { position: el.dataset.position || '' }); });
});

// 区画が画面に入ったとき（1 訪問につき区画ごとに 1 回）
var seen = {};
var io = new IntersectionObserver(function (entries) {
  entries.forEach(function (e) {
    var s = e.target.dataset.section;
    if (e.isIntersecting && !seen[s]) { seen[s] = true; trackCv('section_view', { section: s }); }
  });
}, { threshold: 0.3 });
document.querySelectorAll('[data-section]').forEach(function (el) { io.observe(el); });

// 最終 CV（送信・友だち追加ボタン・電話番号のタップ）
document.querySelectorAll('form[data-cv-form]').forEach(function (f) {
  f.addEventListener('submit', function () { trackCv(f.dataset.cvForm); });
});

// フォームに最初に触れたとき
var started = false;
document.querySelectorAll('form input, form select, form textarea').forEach(function (el) {
  el.addEventListener('focus', function () { if (!started) { started = true; trackCv('form_start'); } });
});
```

## 確かめる項目

- 静的: 計測の経路が 1 つ以上あり、ID がプレースホルダのままではない／同じ計測を二重に入れていない／GTM なら `<body>` 直後の noscript もある／
  CTA に `data-cv` が付いている／`trackCv` が定義され、タグはそこからだけ呼ばれている／`utm_*`・`gclid`・`fbclid` を隠し項目に入れている／
  すべてのイベントに `variant` が付く／フォームの送信先が確定している（未定なら「意図的な未設定」）
- 実発火: ページを開いたとき、GTM（`googletagmanager.com/gtm.js`）か GA4（`google-analytics.com/g/collect`）か Meta（`facebook.com/tr`）への
  リクエストが出る／CTA を押したとき、計測のリクエストが出る／スマホの幅（390px）で文字がはみ出していない／JavaScript のエラーが出ていない
