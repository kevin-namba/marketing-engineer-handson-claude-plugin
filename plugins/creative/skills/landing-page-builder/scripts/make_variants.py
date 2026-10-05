#!/usr/bin/env python3
"""ベース LP から訴求違いのバリアントを量産する（LPテスト用）。

ベースの index.html に仕込んだスロットコメントの中身だけを差し替える。

    <!-- lp:headline -->3日で予約が埋まる<!-- /lp:headline -->

Usage:
    python3 make_variants.py --base lp/a --spec lp/variants.yaml \\
        --out lp --json

spec (YAML または JSON。PyYAML が無ければ JSON のみ):

    variants:
      - id: b
        note: 価格訴求
        slots:
          headline: "初期費用0円ではじめる集客"
      - id: c
        note: 実績訴求
        slots:
          headline: "導入◯◯店舗が使う集客の仕組み"

1 バリアントで複数スロットを変えると「何が効いたか」が分からなくなるため既定で警告する
（意図的なら --allow-multi）。

--json 指定時は失敗しても終了コード 0 で {"error": "..."} を返す。
呼び出し側は必ず JSON の "error" を読むこと。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys

SLOT_RE_TMPL = r"(<!--\s*lp:{name}\s*-->)(.*?)(<!--\s*/lp:{name}\s*-->)"
VARIANT_MARK = "<!-- lp-generate:variant -->"


def load_spec(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()

    if path.lower().endswith((".yaml", ".yml")):
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "YAML を読むには PyYAML が要る（pip install pyyaml）。"
                "入れられない場合は spec を JSON で書いて .json で渡す"
            ) from exc
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)

    if not isinstance(data, dict) or not isinstance(data.get("variants"), list):
        raise RuntimeError("spec の形式が不正。トップレベルに variants(list) が要る")
    return data


def find_slots(html: str) -> set[str]:
    return set(re.findall(r"<!--\s*lp:([a-z0-9_-]+)\s*-->", html, re.I))


def replace_slot(html: str, name: str, value: str) -> tuple[str, bool]:
    pattern = SLOT_RE_TMPL.format(name=re.escape(name))
    new_html, n = re.subn(
        pattern,
        lambda m: m.group(1) + value + m.group(3),
        html,
        flags=re.I | re.S,
    )
    return new_html, n > 0


def inject_variant_id(html: str, variant_id: str) -> str:
    """バリアント識別子を JS 変数と dataLayer に載せる。

    レポート時に「どのバリアントの CV か」を分けられないとテストが成立しない。
    """
    if VARIANT_MARK in html:
        html = re.sub(
            rf'{re.escape(VARIANT_MARK)}.*?{re.escape(VARIANT_MARK)}',
            _variant_block(variant_id),
            html,
            flags=re.S,
        )
        return html

    block = _variant_block(variant_id)
    if re.search(r"</head>", html, re.I):
        return re.sub(r"</head>", block + "\n</head>", html, count=1, flags=re.I)
    return block + "\n" + html


def _variant_block(variant_id: str) -> str:
    return (
        f"{VARIANT_MARK}\n"
        "<script>\n"
        f'  window.LP_VARIANT = "{variant_id}";\n'
        "  window.dataLayer = window.dataLayer || [];\n"
        f'  window.dataLayer.push({{ lp_variant: "{variant_id}" }});\n'
        "</script>\n"
        f"{VARIANT_MARK}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="ベース LP から LPテスト用バリアントを量産する")
    ap.add_argument("--base", required=True, help="ベース LP のディレクトリ（index.html を含む）")
    ap.add_argument("--spec", required=True, help="バリアント定義 (YAML/JSON)")
    ap.add_argument("--out", required=True, help="出力先ディレクトリ（配下に <id>/ を作る）")
    ap.add_argument("--allow-multi", action="store_true", help="1バリアントで複数スロット変更を許可する")
    ap.add_argument("--force", action="store_true", help="既存の出力ディレクトリを上書きする")
    ap.add_argument("--json", action="store_true", dest="as_json", help="JSON で出力する")
    args = ap.parse_args()

    def fail(msg: str) -> int:
        if args.as_json:
            print(json.dumps({"error": msg}, ensure_ascii=False, indent=2))
            return 0  # --json では常に 0。呼び出し側は error を読むこと
        print(f"Error: {msg}", file=sys.stderr)
        return 1

    base_html_path = os.path.join(args.base, "index.html")
    if not os.path.isfile(base_html_path):
        return fail(f"ベースの index.html が見つからない: {base_html_path}")

    try:
        spec = load_spec(args.spec)
    except (OSError, ValueError, RuntimeError) as exc:
        return fail(f"spec の読み込みに失敗した: {exc}")

    with open(base_html_path, encoding="utf-8") as fh:
        base_html = fh.read()

    available = find_slots(base_html)
    if not available:
        return fail(
            "ベース HTML にスロットコメントが無い。"
            "差し替えたい箇所を <!-- lp:headline -->…<!-- /lp:headline --> で囲むこと"
        )

    results = []
    warnings = []

    for idx, v in enumerate(spec["variants"]):
        vid = str(v.get("id") or "").strip()
        if not vid or not re.fullmatch(r"[a-z0-9_-]+", vid, re.I):
            warnings.append(f"variants[{idx}]: id が不正なのでスキップした（英数字/ハイフン/アンダースコアのみ）")
            continue

        slots = v.get("slots") or {}
        if not isinstance(slots, dict) or not slots:
            warnings.append(f"{vid}: slots が空なのでスキップした")
            continue

        unknown = set(slots) - available
        if unknown:
            warnings.append(
                f"{vid}: ベースに存在しないスロット {', '.join(sorted(unknown))} を指定している（無視した）"
            )

        applicable = {k: val for k, val in slots.items() if k in available}
        if not applicable:
            warnings.append(f"{vid}: 適用できるスロットが無いのでスキップした")
            continue

        if len(applicable) > 1 and not args.allow_multi:
            warnings.append(
                f"{vid}: {len(applicable)}個のスロットを同時に変更している"
                f"（{', '.join(sorted(applicable))}）。どれが効いたか判別できない。"
                "意図的なら --allow-multi を付ける"
            )

        dest = os.path.join(args.out, vid)
        if os.path.abspath(dest) == os.path.abspath(args.base):
            warnings.append(f"{vid}: 出力先がベースと同一なのでスキップした（上書き事故防止）")
            continue
        if os.path.exists(dest):
            if not args.force:
                warnings.append(f"{vid}: 出力先が既に存在するのでスキップした（上書きするなら --force）")
                continue
            shutil.rmtree(dest)

        shutil.copytree(args.base, dest)

        html = base_html
        applied = []
        for name, value in applicable.items():
            html, ok = replace_slot(html, name, str(value))
            if ok:
                applied.append(name)
            else:
                warnings.append(f"{vid}: スロット {name} の置換に失敗した")
        html = inject_variant_id(html, vid)

        with open(os.path.join(dest, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(html)

        results.append(
            {
                "id": vid,
                "note": v.get("note", ""),
                "path": os.path.abspath(dest),
                "url_param": f"?lp={vid}",
                "changed_slots": sorted(applied),
            }
        )

    # ベース側にも識別子を入れておかないと、対照群の CV が分離できない。
    base_id = str(spec.get("base_id") or os.path.basename(os.path.normpath(args.base)))
    base_out = inject_variant_id(base_html, base_id)
    if base_out != base_html:
        with open(base_html_path, "w", encoding="utf-8") as fh:
            fh.write(base_out)

    summary_path = os.path.join(args.out, "variants.md")
    try:
        with open(summary_path, "w", encoding="utf-8") as fh:
            fh.write("# LPテスト バリアント一覧\n\n")
            fh.write(f"ベース: `{base_id}` / スロット: {', '.join(sorted(available))}\n\n")
            fh.write("| ID | 訴求 | 変更スロット | URL パラメータ |\n|---|---|---|---|\n")
            fh.write(f"| {base_id} | （対照群） | - | `?lp={base_id}` |\n")
            for r in results:
                fh.write(
                    f"| {r['id']} | {r['note'] or '-'} | {', '.join(r['changed_slots']) or '-'} | `{r['url_param']}` |\n"
                )
            fh.write(
                "\n## 判定ルール\n\n"
                "- 同一期間・同額・同一クリエイティブで配信する\n"
                "- 判定に使う成果がどちらかの案で 50 件に満たないうちは、勝ち負けを決めない（数十クリックの差は偶然でも起きる）\n"
                "- 勝ち負けは、始める前に決めた基準（申し込みの件数や割合）で決める。クリック率だけで判断しない\n"
                "- 1 つの案で変えるのは 1 か所だけ\n"
            )
    except OSError as exc:
        warnings.append(f"variants.md の書き出しに失敗した: {exc}")

    out = {
        "base": os.path.abspath(args.base),
        "base_id": base_id,
        "available_slots": sorted(available),
        "created": results,
        "summary": summary_path,
        "warnings": warnings,
    }

    if args.as_json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    for r in results:
        print(f"[OK] {r['id']}: {r['path']}  ({', '.join(r['changed_slots'])})")
    for w in warnings:
        print(f"[WARN] {w}")
    print(f"\n{len(results)}件を作成した。一覧: {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
