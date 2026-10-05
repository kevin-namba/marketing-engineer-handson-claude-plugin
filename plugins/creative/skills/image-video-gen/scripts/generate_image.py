#!/usr/bin/env python3
"""画像生成 API（Gemini / OpenAI）で画像を作り、隣に履歴（サイドカー）を書く。

標準ライブラリだけで動く。認証情報は環境変数から読む。

    GEMINI_API_KEY   … --provider gemini のとき
    OPENAI_API_KEY   … --provider openai のとき
    GEMINI_IMAGE_MODEL / OPENAI_IMAGE_MODEL … モデル名の上書き（任意）

使い方::

    python3 generate_image.py --provider gemini --prompt-file spec.json \\
        --out out/yoyaku3d_after_catch_meta_1080x1080_v01.png --aspect 1:1 --size 2K
    python3 generate_image.py --provider openai --prompt-file spec.json \\
        --out out/flow.png --size 1536x1024 --quality high
    python3 generate_image.py --provider openai --prompt "右下に「平日限定」のバッジを重ねる。ほかは変えない" \\
        --out out/banner_v02.png --ref out/banner_v01.png \\
        --variant-of cr_0187 --changed badge

結果は JSON で標準出力に出る。失敗したときは ``{"error": ..., "hint": ...}`` を出し、
**画像ファイルを書かない**（中身が空の画像が成果物に混ざるのを防ぐ）。終了コードは成功 0・失敗 1。

サイドカー（``<画像ファイル名>.json``）には「どのモデルに何を投げたか」が入る。
このスクリプトが自動で書くので、手で書かない・書き換えない。

API の仕様（エンドポイント・パラメータ・モデル名）は執筆時点のもの。変わりうるので、
エラーが出たら公式ドキュメントで確認する:
  Gemini: https://ai.google.dev/gemini-api/docs/image-generation
  OpenAI: https://developers.openai.com/api/docs/guides/image-generation
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
OPENAI_BASE = "https://api.openai.com/v1"

# 執筆時点の既定。提供元がモデルを入れ替えたら環境変数か --model で上書きする。
DEFAULT_MODELS = {"gemini": "gemini-3.1-flash-image", "openai": "gpt-image-2"}
MODEL_ENV = {"gemini": "GEMINI_IMAGE_MODEL", "openai": "OPENAI_IMAGE_MODEL"}
KEY_ENV = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY"}

IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
OPENAI_FORMAT = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp"}
SIDECAR_SUFFIX = ".json"


def emit(payload: dict[str, Any], code: int = 0) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    raise SystemExit(code)


def die(message: str, **extra: Any) -> None:
    emit({"error": message, **extra}, code=1)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def http(url: str, *, headers: dict[str, str], body: bytes, content_type: str, timeout: int) -> tuple[int, Any, str]:
    """(status, JSON, 生テキスト) を返す。status 0 は接続の失敗。"""
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", content_type)
    for key, value in headers.items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace") if exc.fp else str(exc)
        status = exc.code
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return 0, None, f"{type(exc).__name__}: {exc}"
    try:
        return status, json.loads(raw), raw
    except json.JSONDecodeError:
        return status, None, raw


def multipart(fields: dict[str, Any], files: list[tuple[str, Path]]) -> tuple[bytes, str]:
    boundary = f"----image-gen-{os.urandom(16).hex()}"
    parts: list[bytes] = []
    for name, value in fields.items():
        if value in (None, ""):
            continue
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(str(value).encode("utf-8") + b"\r\n")
    for name, path in files:
        mime = IMAGE_MIME.get(path.suffix.lower(), "application/octet-stream")
        parts.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
                f'filename="{path.name}"\r\nContent-Type: {mime}\r\n\r\n'
            ).encode()
        )
        parts.append(path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def collect_images(node: Any, found: list[str]) -> None:
    """レスポンスの中から base64 の画像データを拾う（キー名ではなく実体の有無で判定する）。"""
    if isinstance(node, list):
        for item in node:
            collect_images(item, found)
        return
    if not isinstance(node, dict):
        return
    mime = node.get("mime_type") or node.get("mimeType") or ""
    data = node.get("data")
    if isinstance(mime, str) and mime.startswith("image/") and isinstance(data, str) and data:
        found.append(data)
    if isinstance(node.get("b64_json"), str) and node["b64_json"]:
        found.append(node["b64_json"])
    for value in node.values():
        if isinstance(value, (dict, list)):
            collect_images(value, found)


def api_message(payload: Any, raw: str) -> str:
    if isinstance(payload, dict):
        detail = payload.get("error")
        if isinstance(detail, dict) and detail.get("message"):
            return str(detail["message"])
    return raw[:500]


def explain_failure(provider: str, status: int, payload: Any, raw: str, model: str) -> None:
    message = api_message(payload, raw)
    if status == 0:
        die(f"{provider} の API に接続できません: {raw}", hint="ネットワークを確かめる。別の経路（もう一方の提供元・HTML）に切り替える")
    if status in (401, 403):
        die(f"API キーが無効か、画像生成が有効になっていません: {message}",
            hint="キーの発行元と有効期限を確かめる。直らなければ、もう一方の提供元か HTML で組む")
    if status == 404:
        die(f"モデルが見つかりません（{model}）: {message}",
            hint=f"モデルは入れ替わる。公式ドキュメントで現行のモデル名を確かめ、--model か {MODEL_ENV[provider]} で指定する")
    if status == 429:
        die(f"レート上限または残高の不足です: {message}", hint="時間を置くか、もう一方の提供元か HTML で組む")
    die(f"HTTP {status}: {message}", hint="サイズ・比率・背景の組み合わせはモデルごとに違う。公式ドキュメントで確かめる")


def numbered(path: Path, index: int, total: int) -> Path:
    return path if total <= 1 else path.with_name(f"{path.stem}-{index + 1}{path.suffix}")


def write_sidecar(path: Path, *, provider: str, model: str, prompt: str, params: dict[str, Any], meta: dict[str, Any]) -> Path:
    sidecar = path.with_name(path.name + SIDECAR_SUFFIX)
    record: dict[str, Any] = {"file": path.name, **meta}
    record["generation"] = {
        "provider": provider,
        "model": model,
        "prompt": prompt,
        # 未指定（空）は落とす。False と 0 は「指定した」なので残す
        "params": {k: v for k, v in params.items() if v not in (None, "", [])},
        "bytes": path.stat().st_size,
        "created_at": now_iso(),
    }
    sidecar.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return sidecar


def parse_meta(args: argparse.Namespace) -> dict[str, Any]:
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
    return meta


def image_files(paths: list[str], label: str) -> list[Path]:
    out: list[Path] = []
    for raw in paths:
        path = Path(raw).expanduser()
        if not path.is_file():
            die(f"{label}が見つかりません: {path}")
        if path.suffix.lower() not in IMAGE_MIME:
            die(f"{label}の形式に対応していません: {path.suffix}", hint=f"対応: {', '.join(sorted(IMAGE_MIME))}")
        out.append(path)
    return out


def run_gemini(args: argparse.Namespace, key: str, model: str, prompt: str, out: Path, refs: list[Path]) -> list[tuple[bytes, dict[str, Any]]]:
    response_format: dict[str, Any] = {"type": "image", "mime_type": IMAGE_MIME[out.suffix.lower()]}
    if args.aspect:
        response_format["aspect_ratio"] = args.aspect
    if args.size:
        response_format["image_size"] = args.size
    blocks: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for ref in refs:
        blocks.append({"type": "image", "mime_type": IMAGE_MIME[ref.suffix.lower()],
                       "data": base64.b64encode(ref.read_bytes()).decode("ascii")})
    body = json.dumps({"model": model, "input": blocks, "response_format": response_format}).encode("utf-8")
    params = {"aspect_ratio": args.aspect, "image_size": args.size, "references": [str(r) for r in refs]}

    results: list[tuple[bytes, dict[str, Any]]] = []
    for _ in range(args.count):  # Gemini は 1 リクエスト 1 枚。枚数ぶんリクエストする
        status, payload, raw = http(f"{GEMINI_BASE}/interactions", headers={"x-goog-api-key": key},
                                    body=body, content_type="application/json", timeout=args.timeout)
        if status == 0 or status >= 400 or payload is None:
            explain_failure("gemini", status, payload, raw, model)
        found: list[str] = []
        collect_images(payload, found)
        if not found:
            die("レスポンスに画像が含まれていませんでした（ファイルは書いていません）",
                hint="安全フィルタで止まった可能性がある。プロンプトを言い換える。レスポンスの形が変わっていないかを公式ドキュメントで確かめる")
        results.append((base64.b64decode(found[-1]), params))  # 途中経過が混ざることがあるので最後の 1 枚
    return results


def run_openai(args: argparse.Namespace, key: str, model: str, prompt: str, out: Path, refs: list[Path], masks: list[Path]) -> list[tuple[bytes, dict[str, Any]]]:
    fields: dict[str, Any] = {
        "model": model, "prompt": prompt, "n": args.count, "size": args.size,
        "quality": args.quality, "background": args.background,
        "output_format": OPENAI_FORMAT[out.suffix.lower()],
    }
    fields = {k: v for k, v in fields.items() if v not in (None, "")}
    headers = {"Authorization": f"Bearer {key}"}
    if refs:  # 参照画像があるときは編集用のエンドポイント
        body, ctype = multipart(fields, [("image[]", p) for p in refs] + [("mask", p) for p in masks])
        status, payload, raw = http(f"{OPENAI_BASE}/images/edits", headers=headers, body=body,
                                    content_type=ctype, timeout=args.timeout)
    else:
        status, payload, raw = http(f"{OPENAI_BASE}/images/generations", headers=headers,
                                    body=json.dumps(fields).encode("utf-8"),
                                    content_type="application/json", timeout=args.timeout)
    if status == 0 or status >= 400 or payload is None:
        explain_failure("openai", status, payload, raw, model)
    found: list[str] = []
    collect_images(payload.get("data") if isinstance(payload, dict) else None, found)
    if not found:
        die("レスポンスに画像が含まれていませんでした（ファイルは書いていません）",
            hint="モデレーションで止まった可能性がある。プロンプトを言い換える。レスポンスの形が変わっていないかを公式ドキュメントで確かめる")
    params = {"size": args.size, "quality": args.quality, "background": args.background,
              "references": [str(r) for r in refs], "mask": str(masks[0]) if masks else "",
              "endpoint": "edits" if refs else "generations"}
    return [(base64.b64decode(data), params) for data in found]


def main() -> None:
    parser = argparse.ArgumentParser(description="画像生成 API で画像を作り、隣に履歴（サイドカー）を書く")
    parser.add_argument("--provider", required=True, choices=("gemini", "openai"))
    parser.add_argument("--prompt", help="生成の指示。--prompt-file と排他")
    parser.add_argument("--prompt-file", help="JSON の設計書などをファイルから読む")
    parser.add_argument("--out", required=True, help="出力ファイル（.png / .jpg / .webp）")
    parser.add_argument("--model", default="", help="モデル名。未指定なら環境変数、無ければ既定")
    parser.add_argument("--aspect", default="", help="gemini のみ。1:1 / 16:9 / 9:16 など")
    parser.add_argument("--size", default="", help="gemini は解像度ティア（1K / 2K など）、openai はピクセル（1024x1024 など）")
    parser.add_argument("--quality", default="", help="openai のみ。auto / low / medium / high")
    parser.add_argument("--background", default="", help="openai のみ。auto / opaque / transparent（モデルによる）")
    parser.add_argument("--ref", action="append", default=[], help="参照画像（複数可）。元の画像を渡して編集するときに使う")
    parser.add_argument("--mask", default="", help="openai のみ。描き直す範囲（透明部分）。--ref と併用")
    parser.add_argument("--count", type=int, default=1, help="枚数（既定 1）")
    parser.add_argument("--timeout", type=int, default=300, help="1 リクエストのタイムアウト秒")
    parser.add_argument("--meta", action="append", default=[],
                        help="サイドカーに入れるメタデータ（key=value。複数可）。例: appeal=yoyaku3d copy_type=after")
    parser.add_argument("--variant-of", default="", help="どのクリエイティブから作ったか（ID かファイル名）")
    parser.add_argument("--changed", default="", help="何を変えたか（カンマ区切り。例: copy）")
    args = parser.parse_args()

    prompt = args.prompt or ""
    if args.prompt_file:
        path = Path(args.prompt_file).expanduser()
        if not path.is_file():
            die(f"--prompt-file が見つかりません: {path}")
        prompt = path.read_text(encoding="utf-8")
    if not prompt.strip():
        die("--prompt か --prompt-file が必要です")
    if args.count < 1:
        die("--count は 1 以上にする")
    if args.mask and not args.ref:
        die("--mask は --ref と一緒に使う", hint="直したい元の画像を --ref に、描き直す範囲を --mask に渡す")
    if args.mask and args.provider != "openai":
        die("--mask は --provider openai のときだけ使える")

    key = (os.environ.get(KEY_ENV[args.provider]) or "").strip()
    if not key:
        die(f"{KEY_ENV[args.provider]} が未設定です",
            hint="もう一方の提供元を試す。API キーが 1 つも無ければ render_html.py で HTML から画像にする")
    model = args.model or (os.environ.get(MODEL_ENV[args.provider]) or "").strip() or DEFAULT_MODELS[args.provider]

    out = Path(args.out).expanduser()
    if not out.suffix:
        out = out.with_suffix(".png")
    out = out.resolve()
    if out.suffix.lower() not in IMAGE_MIME:
        die(f"出力の拡張子に対応していません: {out.suffix}", hint=f"対応: {', '.join(sorted(IMAGE_MIME))}")

    meta = parse_meta(args)
    refs = image_files(args.ref, "参照画像")
    masks = image_files([args.mask], "マスク画像") if args.mask else []
    if refs:
        meta.setdefault("edited_from", [str(r) for r in refs])  # 編集元を履歴に残す

    if args.provider == "gemini":
        results = run_gemini(args, key, model, prompt, out, refs)
    else:
        results = run_openai(args, key, model, prompt, out, refs, masks)

    saved: list[dict[str, str]] = []
    for index, (data, params) in enumerate(results):
        if not data:
            die("画像のデータが空でした（ファイルは書いていません）", saved=saved)
        target = numbered(out, index, len(results))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        sidecar = write_sidecar(target, provider=args.provider, model=model, prompt=prompt, params=params, meta=meta)
        saved.append({"file": str(target), "sidecar": str(sidecar)})

    emit({
        "ok": True,
        "provider": args.provider,
        "model": model,
        "files": saved,
        "note": "生成画像です。開いて全文字を読んでから使う。実在の店舗・人物・提供物の代わりに使わない",
    })


if __name__ == "__main__":
    main()
