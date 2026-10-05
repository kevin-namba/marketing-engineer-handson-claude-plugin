#!/usr/bin/env python3
"""HTML/CSS で組んだバナー・図解を画像にし、隣に履歴（サイドカー）を書く。

画像生成の API キーが無いとき、実在の写真の上に帯と文字を重ねるとき、
同じデザインで中身だけを差し替えて量産するときに使う。

要るもの: ヘッドレスブラウザと日本語フォント。Playwright（``pip install playwright &&
playwright install chromium``）があればそれを使い、はみ出しと画像の引き伸ばしも調べる。
無ければ、入っている Chrome / Chromium のヘッドレス撮影を使う（この場合、はみ出しは自動で調べない）。

使い方::

    python3 render_html.py --html banner.html --out out/banner_1080x1080_v01.png \\
        --width 1080 --height 1080 --scale 2 --meta appeal=yoyaku3d --meta layout_type=catchcopy

結果は JSON で標準出力に出る。失敗したときは ``{"error": ..., "hint": ...}`` を出し、終了コード 1。

サイドカー（``<画像ファイル名>.json``）の generation.prompt には、組んだ HTML の全文が入る
（生成 API のプロンプトと同じ役割。HTML が残っていれば同じ画像を作り直せる）。

既存の Web ページの撮影には使わない。撮ったページは自社の広告に使ってよい素材ではないので、
このスクリプトはローカルの HTML ファイルだけを受け取る。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SIDECAR_SUFFIX = ".json"

# 検品の材料: 画面の外にはみ出した文字と、元の解像度より引き伸ばした画像
CHECK_JS = """() => {
  const out = [];
  const W = window.innerWidth, H = window.innerHeight, dpr = window.devicePixelRatio || 1;
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    if (el.children.length === 0 && el.textContent.trim() &&
        (r.right > W + 1 || r.bottom > H + 1 || r.left < -1 || r.top < -1)) {
      out.push({kind: 'overflow', text: el.textContent.trim().slice(0, 30)});
    }
    if (el.tagName === 'IMG' && el.naturalWidth && r.width * dpr > el.naturalWidth * 1.05) {
      out.push({kind: 'upscaled_image', src: (el.getAttribute('src') || '').slice(0, 80),
                natural_width: el.naturalWidth, shown_px: Math.round(r.width * dpr)});
    }
  }
  return out.slice(0, 20);
}"""

CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)


def find_chrome() -> str:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    for path in CHROME_CANDIDATES:
        if Path(path).is_file():
            return path
    return ""



def emit(payload: dict[str, Any], code: int = 0) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    raise SystemExit(code)


def die(message: str, **extra: Any) -> None:
    emit({"error": message, **extra}, code=1)


def main() -> None:
    parser = argparse.ArgumentParser(description="HTML/CSS を画像にし、隣に履歴（サイドカー）を書く")
    parser.add_argument("--html", required=True, help="画像にするローカルの HTML ファイル")
    parser.add_argument("--out", required=True, help="出力先の PNG")
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--scale", type=int, default=2, help="解像度の倍率（既定 2。等倍は文字の輪郭が甘くなる）")
    parser.add_argument("--settle-ms", type=int, default=1500, help="描画を待つ時間（ミリ秒）")
    parser.add_argument("--meta", action="append", default=[], help="サイドカーに入れるメタデータ（key=value。複数可）")
    parser.add_argument("--variant-of", default="", help="どのクリエイティブから作ったか")
    parser.add_argument("--changed", default="", help="何を変えたか（カンマ区切り）")
    args = parser.parse_args()

    html_path = Path(args.html).expanduser().resolve()
    if not html_path.is_file():
        die(f"HTML ファイルがありません: {html_path}")
    out = Path(args.out).expanduser().resolve()
    if out.suffix.lower() != ".png":
        out = out.with_suffix(".png")

    meta: dict[str, Any] = {}
    for item in args.meta:
        if "=" not in item:
            die(f"--meta は key=value の形で渡す: {item}")
        key, value = item.split("=", 1)
        meta[key.strip()] = value.strip()
    if args.variant_of:
        meta["variant_of"] = args.variant_of
    if args.changed:
        meta["changed"] = [c.strip() for c in args.changed.split(",") if c.strip()]

    out.parent.mkdir(parents=True, exist_ok=True)
    warnings: list[dict[str, Any]] = []
    engine = "playwright"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sync_playwright = None  # type: ignore[assignment]

    if sync_playwright is not None:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(locale="ja-JP",
                                        viewport={"width": args.width, "height": args.height},
                                        device_scale_factor=args.scale)
                try:
                    page.goto(html_path.as_uri(), wait_until="networkidle", timeout=30_000)
                    page.wait_for_timeout(args.settle_ms)
                    warnings = page.evaluate(CHECK_JS)
                    page.screenshot(path=str(out), full_page=False)
                finally:
                    browser.close()
        except Exception as exc:  # noqa: BLE001
            out.unlink(missing_ok=True)
            die(f"{type(exc).__name__}: {exc}", hint="Chromium が入っているか（playwright install chromium）を確かめる")
    else:
        # Playwright が無いときは、入っている Chrome / Chromium のヘッドレス撮影を使う
        engine = "chrome-cli"
        binary = find_chrome()
        if not binary:
            die("Playwright も Chrome / Chromium も見つかりません",
                hint="pip install playwright && playwright install chromium。入れられない環境では、HTML と JSON の設計書を納品し「画像化は未実施」と書く")
        cmd = [binary, "--headless=new", "--hide-scrollbars", "--disable-gpu",
               f"--window-size={args.width},{args.height}",
               f"--force-device-scale-factor={args.scale}",
               f"--virtual-time-budget={max(args.settle_ms, 1000)}",
               f"--screenshot={out}", html_path.as_uri()]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as exc:
            out.unlink(missing_ok=True)
            die(f"{type(exc).__name__}: {exc}")
        if proc.returncode != 0 and not out.exists():
            die(f"Chrome の撮影に失敗しました: {proc.stderr.strip()[-300:]}")
        warnings = [{"kind": "not_checked",
                     "detail": "この経路でははみ出しと画像の引き伸ばしを自動で調べていない。画像を開いて確かめる"}]

    if not out.exists() or out.stat().st_size == 0:
        out.unlink(missing_ok=True)
        die("画像を書き出せませんでした（ファイルは残していません）")

    record: dict[str, Any] = {"file": out.name, **meta}
    record["generation"] = {
        "provider": "html",
        "model": engine,
        "prompt": html_path.read_text(encoding="utf-8", errors="replace"),
        "params": {"width": args.width, "height": args.height, "scale": args.scale, "html": str(html_path)},
        "bytes": out.stat().st_size,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    sidecar = out.with_name(out.name + SIDECAR_SUFFIX)
    sidecar.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    emit({
        "ok": True,
        "file": str(out),
        "sidecar": str(sidecar),
        "engine": engine,
        "warnings": warnings,
        "note": "warnings が空でも、画像を開いて折り返しと実寸での読みやすさを確かめる",
    })


if __name__ == "__main__":
    main()
