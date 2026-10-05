#!/usr/bin/env python3
"""LP の計測タグと、広告の遷移先としての最低限の要件を検証する。

「タグを書いた」と「タグが実際に発火する」は別物なので、2 段階で見る。

  静的チェック (既定)  : HTML を読んで、必要な要素が書かれているかを見る。依存なし。
  実発火チェック (--live): ローカル HTTP サーバで開き、CTA を実際にクリックして
                           計測ビーコンが飛ぶかをネットワークレベルで観測する。
                           Playwright が要る。無ければ静的チェックだけを行い、その旨を notes に書く。

Usage:
    python3 verify_tags.py --path lp/a/index.html --json
    python3 verify_tags.py --path lp/a/index.html --live --json

--json 指定時は失敗しても終了コード 0 で {"error": "..."} を返す。
呼び出し側は必ず JSON の "error" と各チェックの "status" を読むこと。

status の意味:
    ok      … 問題なし
    warn    … 改善余地（動くが、表示速度や申し込み率に効く）
    missing … 欠落。このまま配信すると損をする
    todo    … 意図的な未設定（プレースホルダが残っている）

missing が 1 つでも残るあいだ、ready_to_run_ads は false になる。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

# ---------------------------------------------------------------------------
# 既知のプレースホルダ。ダミー ID を「設定済み」と誤判定しないために持つ。
# ---------------------------------------------------------------------------
PLACEHOLDER_PATTERNS = [
    r"GTM-XXXX+",
    r"G-XXXX+",
    r"AW-XXXX+",
    r"\bXXXXXXXXXX\b",
    r"\b1234567890\b",
    r"YOUR_PIXEL_ID",
    r"YOUR_GTM_ID",
    r"YOUR_GA4_ID",
]

# 計測ビーコンの宛先。--live のネットワーク観測で使う。
BEACON_HOSTS = {
    "ga4": ("google-analytics.com/g/collect", "analytics.google.com/g/collect"),
    "gtm": ("googletagmanager.com/gtm.js", "googletagmanager.com/gtag/js"),
    "meta": ("facebook.com/tr", "facebook.net/signals"),
}


def _check(cid: str, label: str, status: str, detail: str) -> dict:
    return {"id": cid, "label": label, "status": status, "detail": detail}


def _has_placeholder(text: str) -> str | None:
    for pat in PLACEHOLDER_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(0)
    return None


# ---------------------------------------------------------------------------
# 静的チェック
# ---------------------------------------------------------------------------
def check_basics(html: str) -> list[dict]:
    out = []

    if re.search(r'<meta[^>]+name=["\']viewport["\']', html, re.I):
        out.append(_check("viewport", "viewport メタタグ", "ok", "あり"))
    else:
        out.append(
            _check("viewport", "viewport メタタグ", "missing", "スマホで表示が崩れる。広告流入はほぼスマホ")
        )

    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if title and title.group(1).strip():
        out.append(_check("title", "title", "ok", title.group(1).strip()[:60]))
    else:
        out.append(_check("title", "title", "missing", "空または未設定"))

    desc = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', html, re.I | re.S
    )
    if desc and desc.group(1).strip():
        out.append(_check("description", "meta description", "ok", desc.group(1).strip()[:60]))
    else:
        out.append(_check("description", "meta description", "warn", "未設定"))

    og_keys = re.findall(r'<meta[^>]+property=["\']og:([a-z_]+)["\']', html, re.I)
    missing_og = {"title", "description", "image"} - {k.lower() for k in og_keys}
    if not missing_og:
        out.append(_check("ogp", "OGP", "ok", "title/description/image あり"))
    else:
        out.append(
            _check("ogp", "OGP", "warn", f"不足: {', '.join(sorted(missing_og))}（SNS共有時の見え方）")
        )

    return out


def check_tags(html: str) -> list[dict]:
    """計測タグ。ダミー ID を ok にしないのがこの関数の主目的。"""
    out = []

    # --- GTM ---
    gtm_ids = set(re.findall(r"GTM-[A-Z0-9]{4,}", html))
    real_gtm = {i for i in gtm_ids if not _has_placeholder(i)}
    if real_gtm:
        has_noscript = "googletagmanager.com/ns.html" in html
        out.append(
            _check(
                "gtm",
                "Google Tag Manager",
                "ok" if has_noscript else "warn",
                f"{', '.join(sorted(real_gtm))}"
                + ("" if has_noscript else " / body の noscript スニペットが無い"),
            )
        )
    elif gtm_ids:
        out.append(_check("gtm", "Google Tag Manager", "todo", f"プレースホルダのまま: {', '.join(gtm_ids)}"))
    else:
        out.append(_check("gtm", "Google Tag Manager", "missing", "未設置"))

    # --- GA4 ---
    ga_ids = set(re.findall(r"\bG-[A-Z0-9]{6,}\b", html))
    real_ga = {i for i in ga_ids if not _has_placeholder(i)}
    if real_ga:
        out.append(_check("ga4", "GA4 (gtag)", "ok", ", ".join(sorted(real_ga))))
    elif ga_ids:
        out.append(_check("ga4", "GA4 (gtag)", "todo", f"プレースホルダのまま: {', '.join(ga_ids)}"))
    else:
        out.append(_check("ga4", "GA4 (gtag)", "missing", "直貼りなし（GTM 側で管理しているなら可）"))

    # --- Meta ピクセル ---
    fbq_init = re.findall(r"fbq\(\s*['\"]init['\"]\s*,\s*['\"]?(\d{8,})['\"]?", html)
    real_fb = [i for i in fbq_init if not _has_placeholder(i)]
    if real_fb:
        out.append(_check("meta_pixel", "Meta ピクセル", "ok", ", ".join(sorted(set(real_fb)))))
    elif "fbq(" in html:
        out.append(_check("meta_pixel", "Meta ピクセル", "todo", "fbq はあるが init の ID がプレースホルダ/未指定"))
    else:
        out.append(_check("meta_pixel", "Meta ピクセル", "missing", "直貼りなし（GTM 側で管理しているなら可）"))

    # GTM 経由（A）と直貼り（B）は排他的な選択肢なので、片方が生きていれば
    # もう片方の欠落はブロッカーではない。効いている経路が1つも無い場合だけが問題。
    routes = [c for c in out if c["id"] in ("gtm", "ga4", "meta_pixel")]
    if any(c["status"] == "ok" for c in routes):
        for c in routes:
            if c["status"] == "missing":
                c["status"] = "warn"
                c["detail"] = "未設置（他経路で計測できているなら可）"
        out.append(_check("measurement_any", "計測経路の有無", "ok", "少なくとも1経路が有効"))
    else:
        out.append(
            _check(
                "measurement_any",
                "計測経路の有無",
                "missing",
                "GTM / GA4 / Meta のいずれも有効な ID が無い。このまま配信すると成果が計測できない",
            )
        )

    return out


def check_conversion(html: str) -> list[dict]:
    out = []

    cv_attrs = re.findall(r'data-cv=["\']([^"\']+)["\']', html)
    if cv_attrs:
        out.append(
            _check("cv_hooks", "CV フック (data-cv)", "ok", f"{len(cv_attrs)}箇所: {', '.join(sorted(set(cv_attrs)))}")
        )
    else:
        out.append(_check("cv_hooks", "CV フック (data-cv)", "missing", "CTA に data-cv が無い。CV が計測されない"))

    if re.search(r"function\s+trackCv|const\s+trackCv|trackCv\s*=", html):
        out.append(_check("track_fn", "trackCv() 集約", "ok", "定義あり"))
    else:
        out.append(
            _check("track_fn", "trackCv() 集約", "warn", "CV 送信が1か所に集約されていない。タグ差し替え時に漏れる")
        )

    # Meta のウェブイベントは1ピクセル8件まで。増えすぎたら合算イベント設定と衝突する。
    distinct = set(cv_attrs)
    if len(distinct) > 8:
        out.append(
            _check(
                "meta_event_cap",
                "Meta イベント上限",
                "warn",
                f"CV イベント種別が {len(distinct)} 件。iOS14以降は1ピクセル8件までなので合算イベント設定と要突合",
            )
        )

    # 広告パラメータの引き継ぎ。無いと CV を媒体に突き合わせられない。
    params = [p for p in ("utm_", "gclid", "fbclid") if p in html]
    if len(params) >= 2:
        out.append(_check("ad_params", "広告パラメータ引き継ぎ", "ok", ", ".join(params)))
    elif params:
        out.append(_check("ad_params", "広告パラメータ引き継ぎ", "warn", f"一部のみ: {', '.join(params)}"))
    else:
        out.append(
            _check("ad_params", "広告パラメータ引き継ぎ", "missing", "utm_/gclid/fbclid を拾っていない。媒体突合ができない")
        )

    forms = re.findall(r"<form[^>]*>", html, re.I)
    if forms:
        unresolved = [f for f in forms if not re.search(r'action=["\'](?!#)[^"\']+["\']', f, re.I)]
        if unresolved:
            out.append(
                _check("form_action", "フォーム送信先", "todo", f"{len(unresolved)}/{len(forms)} 件が未確定 (action 未設定 or #)")
            )
        else:
            out.append(_check("form_action", "フォーム送信先", "ok", f"{len(forms)}件すべて設定済み"))
    else:
        out.append(_check("form_action", "フォーム送信先", "warn", "form 要素なし（電話/LINE等が CV ならこれで良い）"))

    return out


def check_ux_perf(html: str) -> list[dict]:
    """表示速度と申し込み率に直結するものだけ見る。"""
    out = []

    if re.search(r'class=["\'][^"\']*fixed[^"\']*bottom-0', html) or re.search(r'position\s*:\s*fixed', html):
        out.append(_check("sticky_cta", "スマホ下部固定CTA", "ok", "あり"))
    else:
        out.append(_check("sticky_cta", "スマホ下部固定CTA", "warn", "見当たらない。スクロール中に CTA が押せない"))

    imgs = re.findall(r"<img[^>]*>", html, re.I)
    if imgs:
        no_dim = [i for i in imgs if not (re.search(r"\bwidth=", i, re.I) and re.search(r"\bheight=", i, re.I))]
        no_alt = [i for i in imgs if not re.search(r"\balt=", i, re.I)]
        no_lazy = [i for i in imgs if not re.search(r'loading=["\'](lazy|eager)', i, re.I)]
        if no_dim:
            out.append(_check("img_dimensions", "画像の width/height", "warn", f"{len(no_dim)}/{len(imgs)}件が未指定（CLS の原因）"))
        else:
            out.append(_check("img_dimensions", "画像の width/height", "ok", f"{len(imgs)}件すべて指定"))
        if no_alt:
            out.append(_check("img_alt", "画像の alt", "warn", f"{len(no_alt)}/{len(imgs)}件が未指定"))
        if no_lazy:
            out.append(_check("img_loading", "画像の loading 属性", "warn", f"{len(no_lazy)}/{len(imgs)}件が未指定"))
    else:
        out.append(_check("img_dimensions", "画像の width/height", "warn", "img 要素なし"))

    fonts = re.findall(r'<link[^>]+href=["\'][^"\']*(?:fonts\.googleapis|fonts\.gstatic|typekit)[^"\']*["\']', html, re.I)
    if fonts:
        out.append(_check("web_fonts", "外部Webフォント", "warn", f"{len(fonts)}件。LCP が伸びる。システムフォント代替を検討"))
    else:
        out.append(_check("web_fonts", "外部Webフォント", "ok", "なし"))

    slots = set(re.findall(r"<!--\s*lp:([a-z0-9_-]+)\s*-->", html, re.I))
    if slots:
        out.append(_check("variant_slots", "バリアント用スロット", "ok", ", ".join(sorted(slots))))
    else:
        out.append(_check("variant_slots", "バリアント用スロット", "warn", "スロットコメントが無い。make_variants.py で量産できない"))

    return out


# ---------------------------------------------------------------------------
# 実発火チェック (--live)
# ---------------------------------------------------------------------------
def check_live(path: str, timeout_ms: int) -> tuple[list[dict], str | None]:
    """ローカル HTTP サーバで開き、CTA をクリックして計測ビーコンを観測する。"""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        return [], (
            "playwright が入っていないので実発火チェックをスキップした。"
            "静的チェックのみの結果である点に注意。導入: pip install playwright && playwright install chromium"
        )

    import functools
    import http.server
    import socketserver
    import threading

    directory = os.path.dirname(os.path.abspath(path))
    filename = os.path.basename(path)

    class _QuietHandler(http.server.SimpleHTTPRequestHandler):
        # 既定実装は stderr にアクセスログを吐き、--json の出力を汚す。
        def log_message(self, *args, **kwargs):  # noqa: D102, ANN002, ANN003
            pass

    handler = functools.partial(_QuietHandler, directory=directory)

    try:
        httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    except OSError as exc:
        return [], f"ローカルサーバを起動できなかった: {exc}"

    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    seen: list[str] = []
    out: list[dict] = []
    note: str | None = None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True)
            page.on("request", lambda r: seen.append(r.url))

            page.goto(f"http://127.0.0.1:{port}/{filename}", wait_until="networkidle", timeout=timeout_ms)
            loaded = list(seen)

            # スマホ幅で文字が切れていないか。
            # **document.scrollWidth だけを見ても分からない。** ヒーローに
            # overflow-hidden が付いていると、横スクロールは出ないまま
            # 見出しの右側が黙って切り落とされる（実測: whitespace-nowrap を
            # 10 文字の句に付けた見出しが 390px で欠けた）。
            # 要素の実ジオメトリを見て、ビューポートを越えるものを名指しする。
            overflow = page.evaluate(
                """() => {
                    const vw = window.innerWidth;
                    const label = el => el.tagName.toLowerCase()
                        + (typeof el.className === 'string' && el.className.trim()
                            ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.')
                            : '');
                    const beyond = [];
                    for (const el of document.querySelectorAll('body *')) {
                        const st = getComputedStyle(el);
                        if (st.display === 'none' || st.visibility === 'hidden') continue;
                        if (st.position === 'fixed') continue;   // 固定CTAは画面内に収める前提
                        const r = el.getBoundingClientRect();
                        if (r.width === 0 || r.height === 0) continue;
                        if (r.right > vw + 1) {
                            beyond.push({ el: label(el), over: Math.round(r.right - vw),
                                          text: (el.textContent || '').trim().slice(0, 24) });
                        }
                    }
                    // 親が溢れていれば子も溢れる。いちばん外側だけ報告する。
                    return {
                        scroll_over: Math.max(0, document.documentElement.scrollWidth - vw),
                        beyond: beyond.slice(0, 3),
                    };
                }"""
            )
            beyond = overflow["beyond"]
            if beyond:
                detail = "; ".join(
                    f"{b['el']} が {b['over']}px はみ出し（{b['text']}…）" for b in beyond
                )
                if not overflow["scroll_over"]:
                    detail += " ※横スクロールは出ないが、内容が切れて読めない"
            else:
                detail = "なし"
            out.append(
                _check(
                    "live_overflow",
                    "[live] スマホ幅のはみ出し (390px)",
                    "ok" if not beyond else "missing",
                    detail,
                )
            )

            for key, hosts in BEACON_HOSTS.items():
                hit = [u for u in loaded if any(h in u for h in hosts)]
                out.append(
                    _check(
                        f"live_load_{key}",
                        f"[live] 読み込み時の {key} 通信",
                        "ok" if hit else "missing",
                        hit[0][:110] if hit else "リクエストが飛んでいない",
                    )
                )

            # CTA を実際に押して CV ビーコンを見る。
            buttons = page.query_selector_all("[data-cv]")
            if not buttons:
                out.append(_check("live_cv", "[live] CV 発火", "missing", "data-cv 要素が無いのでクリック検証できない"))
            else:
                before = len(seen)
                clicked = 0
                for btn in buttons[:5]:
                    try:
                        btn.click(timeout=2000, force=True)
                        clicked += 1
                        page.wait_for_timeout(400)
                    except Exception:
                        continue
                fired = [u for u in seen[before:] if any(h in u for grp in BEACON_HOSTS.values() for h in grp)]
                out.append(
                    _check(
                        "live_cv",
                        "[live] CV 発火",
                        "ok" if fired else "missing",
                        f"{clicked}個クリック / 計測リクエスト {len(fired)}件"
                        + ("" if fired else "。data-cv はあるが何も送信していない"),
                    )
                )

            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.wait_for_timeout(300)
            if errors:
                out.append(_check("live_js_error", "[live] JS エラー", "warn", "; ".join(errors[:3])))

            browser.close()
    except Exception as exc:  # noqa: BLE001 - 検証失敗そのものを結果として返す
        note = f"実発火チェック中に失敗した: {type(exc).__name__}: {exc}"
    finally:
        httpd.shutdown()
        httpd.server_close()

    return out, note


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="生成した LP の計測タグ・広告LP要件を検証する")
    ap.add_argument("--path", required=True, help="検証する index.html のパス")
    ap.add_argument("--live", action="store_true", help="Playwright で実際にクリックして発火を観測する")
    ap.add_argument("--timeout", type=int, default=15000, help="--live のタイムアウト(ms)")
    ap.add_argument("--json", action="store_true", dest="as_json", help="JSON で出力する")
    args = ap.parse_args()

    def fail(msg: str) -> int:
        if args.as_json:
            print(json.dumps({"error": msg, "path": args.path}, ensure_ascii=False, indent=2))
            return 0  # --json では常に 0。呼び出し側は error を読むこと
        print(f"Error: {msg}", file=sys.stderr)
        return 1

    if not os.path.isfile(args.path):
        return fail(f"ファイルが見つからない: {args.path}")

    try:
        with open(args.path, encoding="utf-8") as fh:
            html = fh.read()
    except OSError as exc:
        return fail(f"読み込みに失敗した: {exc}")
    except UnicodeDecodeError as exc:
        return fail(f"UTF-8 として読めない: {exc}")

    checks: list[dict] = []
    checks += check_basics(html)
    checks += check_tags(html)
    checks += check_conversion(html)
    checks += check_ux_perf(html)

    notes: list[str] = []
    if args.live:
        live_checks, note = check_live(args.path, args.timeout)
        checks += live_checks
        if note:
            notes.append(note)

    counts = {s: sum(1 for c in checks if c["status"] == s) for s in ("ok", "warn", "missing", "todo")}
    blocking = [c for c in checks if c["status"] == "missing"]

    result = {
        "path": os.path.abspath(args.path),
        "live": bool(args.live),
        "summary": counts,
        "blocking": [c["id"] for c in blocking],
        "ready_to_run_ads": not blocking,
        "checks": checks,
        "notes": notes,
    }

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    icon = {"ok": "OK  ", "warn": "WARN", "missing": "MISS", "todo": "TODO"}
    for c in checks:
        print(f"[{icon[c['status']]}] {c['label']}: {c['detail']}")
    for n in notes:
        print(f"\n! {n}")
    print(f"\nok={counts['ok']} warn={counts['warn']} missing={counts['missing']} todo={counts['todo']}")
    if blocking:
        print(f"配信前に埋めるべき欠落: {', '.join(c['id'] for c in blocking)}")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
