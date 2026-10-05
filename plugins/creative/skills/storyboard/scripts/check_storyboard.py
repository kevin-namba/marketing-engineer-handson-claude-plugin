#!/usr/bin/env python3
"""storyboard.json（編集依頼書の中間データ）を検算し、Markdown / CSV に書き出す。

標準ライブラリだけで動く。JSON の形は references/storyboard-format.md を参照。

使い方::

    python3 check_storyboard.py storyboard.json                 # 検算だけ
    python3 check_storyboard.py storyboard.json --md out/brief.md
    python3 check_storyboard.py storyboard.json --csv out/cuts.csv

検算する項目（WARN として出す。書き出しは止めない）:

* ナレーションが 1 秒 5 文字（--narration-cps）、テロップが 1 秒 4 文字（--telop-cps）を超えるカット
* 文字数の欄と、実際の文字数のずれ
* フックが 3 案あるか。本編と CTA があるか
* 実際に書き出す 1 本ぶんの尺（本編 + CTA + フック 1 案）が、指定の尺に収まるか
* カット尺の平均が 2〜3 秒、最長 5 秒以内か（備考に理由があれば例外として扱う）
* 編集指示に数値が無いカット、フックの 1 カット目にテロップが無い案

終了コード: WARN が 0 件なら 0、1 件以上なら 2、入力の誤りは 1。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

HEADER = ["カット", "区分", "尺(秒)", "映像", "テロップ", "セリフ／ナレーション", "文字数",
          "音", "演出意図", "編集指示", "素材", "撮影が必要", "備考"]
KEYS = ["cut", "phase", "sec", "visual", "telop", "narration", "chars",
        "sound", "intent", "edit_note", "asset", "needs_shoot", "remarks"]
PUNCT = "、。！？!?,.・「」『』（）() 　\n"
VAGUE = ("テンポよく", "いい感じ", "よしなに", "適宜", "かっこよく", "おしゃれに")


def cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "要" if value else ""
    return str(value)


def spoken(text: str) -> str:
    """句読点・かっこ・空白を除いた、読まれる文字。"""
    text = (text or "").replace("（無音）", "")
    return "".join(ch for ch in text if ch not in PUNCT)


def telop_text(text: str) -> str:
    """テロップの文言から、かっこ書きの装飾指定（太字・赤・中央上 など）を除く。"""
    text = re.sub(r"[（(][^（）()]*[）)]", "", text or "")
    return "".join(ch for ch in text if ch not in PUNCT)


def phase_kind(phase: str) -> str:
    p = (phase or "").strip()
    if p.startswith(("フック", "Hook", "hook")):
        return "hook"
    if "CTA" in p.upper():
        return "cta"
    return "body"


def validate(sb: dict[str, Any], narration_cps: float, telop_cps: float) -> tuple[list[str], dict[str, Any]]:
    warns: list[str] = []
    cuts = sb.get("cuts")
    if not isinstance(cuts, list) or not cuts:
        raise ValueError("cuts（カットの配列）がありません")

    hook_sec: dict[str, float] = {}
    shared_sec = 0.0
    shoot: list[str] = []
    kinds = set()
    secs: list[float] = []

    for c in cuts:
        cut_id = cell(c.get("cut")) or "?"
        phase = cell(c.get("phase"))
        kind = phase_kind(phase)
        kinds.add(kind)
        try:
            sec = float(c.get("sec") or 0)
        except (TypeError, ValueError):
            warns.append(f"カット {cut_id}: 尺が数値ではありません（{c.get('sec')!r}）")
            sec = 0.0
        if sec <= 0:
            warns.append(f"カット {cut_id}: 尺が書かれていません")
        secs.append(sec)
        if kind == "hook":
            hook_sec[phase] = hook_sec.get(phase, 0.0) + sec
        else:
            shared_sec += sec

        narr = spoken(cell(c.get("narration")))
        telop = telop_text(cell(c.get("telop")))
        chars = c.get("chars")
        if chars not in (None, "") and abs(int(chars) - len(narr)) > 2:
            warns.append(f"カット {cut_id}: 文字数の欄 {chars} と、実際の文字数 {len(narr)} がずれています")
        if sec > 0 and narr and len(narr) > sec * narration_cps + 0.5:
            warns.append(f"カット {cut_id}: ナレーション {len(narr)} 字が、尺 {sec:g} 秒 × {narration_cps:g} 字を超えています")
        if sec > 0 and telop and len(telop) > sec * telop_cps + 0.5:
            warns.append(f"カット {cut_id}: テロップ {len(telop)} 字が、尺 {sec:g} 秒 × {telop_cps:g} 字を超えています")
        if sec > 5 and not cell(c.get("remarks")):
            warns.append(f"カット {cut_id}: 尺 {sec:g} 秒（最長 5 秒を超える。例外なら備考に理由を書く）")

        edit = cell(c.get("edit_note"))
        if edit and not re.search(r"\d", edit):
            warns.append(f"カット {cut_id}: 編集指示に数値がありません（秒数・間隔・倍率で書く）")
        if any(word in edit for word in VAGUE):
            warns.append(f"カット {cut_id}: 編集指示にあいまいな言葉があります（{edit[:20]}…）")
        if not cell(c.get("visual")):
            warns.append(f"カット {cut_id}: 映像の欄が空です")
        if c.get("needs_shoot"):
            shoot.append(cut_id)
        elif not cell(c.get("asset")) and kind != "cta":
            warns.append(f"カット {cut_id}: 素材の場所が無く、「撮影が必要」の印もありません")

    # フックの 1 カット目にテロップがあるか
    seen: set[str] = set()
    for c in cuts:
        phase = cell(c.get("phase"))
        if phase_kind(phase) == "hook" and phase not in seen:
            seen.add(phase)
            if not telop_text(cell(c.get("telop"))):
                warns.append(f"{phase}: 1 カット目にテロップがありません（音を消すと何の動画か分からない）")

    if len(hook_sec) < 3:
        warns.append(f"フックが {len(hook_sec)} 案です（3 案が基本。本編と CTA は共通）")
    if "body" not in kinds:
        warns.append("本編のカットがありません")
    if "cta" not in kinds:
        warns.append("CTA のカットがありません")
    if hook_sec and max(hook_sec.values()) - min(hook_sec.values()) > 0.5:
        warns.append(f"フックの尺が案ごとに違います（{ {k: round(v, 1) for k, v in hook_sec.items()} }）。揃えると比べやすい")

    effective = shared_sec + (max(hook_sec.values()) if hook_sec else 0.0)
    target = (sb.get("meta") or {}).get("duration_sec")
    if target:
        try:
            target_f = float(target)
            if effective > target_f * 1.1 + 0.01:
                warns.append(f"1 本ぶんの尺 {effective:g} 秒が、指定 {target_f:g} 秒の 1 割増しを超えています")
            elif effective < target_f * 0.8:
                warns.append(f"1 本ぶんの尺 {effective:g} 秒が、指定 {target_f:g} 秒より 2 割以上短いです（素材が薄いなら、短くした理由を書く）")
        except (TypeError, ValueError):
            warns.append(f"meta.duration_sec が数値ではありません（{target!r}）")
    else:
        warns.append("meta.duration_sec（指定の尺）がありません")

    valid = [s for s in secs if s > 0]
    avg = sum(valid) / len(valid) if valid else 0.0
    if valid and not 1.0 <= avg <= 3.5:
        warns.append(f"カット尺の平均が {avg:.1f} 秒です（2〜3 秒が目安）")

    summary = {
        "cuts": len(cuts),
        "hook_variants": sorted(hook_sec),
        "effective_duration_sec": round(effective, 2),
        "avg_cut_sec": round(avg, 2),
        "needs_shoot": shoot,
    }
    return warns, summary


def render_md(sb: dict[str, Any], summary: dict[str, Any], warns: list[str]) -> str:
    meta = sb.get("meta") or {}
    lines = [f"# 編集依頼書: {meta.get('title', '（無題）')}", ""]
    for label, key in (("商材", "product"), ("オファー", "offer"), ("訴求軸", "appeal"),
                       ("尺", "duration_sec"), ("媒体", "media"), ("書き出し設定", "export")):
        if meta.get(key) not in (None, ""):
            lines.append(f"- {label}: {meta[key]}")
    lines += ["", "## 仕上がりの方針と参考にする広告", ""]
    lines += [f"- {p}" for p in sb.get("policy", [])] or ["- （未記入）"]
    for ref in sb.get("references", []):
        lines.append(f"- 参考: {ref.get('url', '')} {ref.get('note', '')}".rstrip())
    lines += ["", "## 申し送り", "", "| 項目 | ルール | 具体例 |", "|---|---|---|"]
    for h in sb.get("handoff", []):
        lines.append(f"| {h.get('item', '')} | {h.get('rule', '')} | {h.get('example', '')} |")
    lines += ["", "## 素材の置き場所", "", "| No | 種別 | 素材名 | 使うカット | 場所 |", "|---|---|---|---|---|"]
    for a in sb.get("assets", []):
        lines.append(f"| {cell(a.get('no'))} | {a.get('type', '')} | {a.get('name', '')} | {a.get('cuts', '')} | {a.get('location', '')} |")
    lines += ["", "## カット表", "", "| " + " | ".join(HEADER) + " |", "|" + "---|" * len(HEADER)]
    for c in sb.get("cuts", []):
        row = [cell(c.get(k)).replace("\n", "<br>").replace("|", "／") for k in KEYS]
        lines.append("| " + " | ".join(row) + " |")
    lines += ["", "## 検算", "",
              f"- 1 本ぶんの尺（本編 + CTA + フック 1 案）: {summary['effective_duration_sec']:g} 秒",
              f"- カット数: {summary['cuts']} ／ カット尺の平均: {summary['avg_cut_sec']:g} 秒",
              f"- フック: {', '.join(summary['hook_variants']) or 'なし'}",
              f"- 撮影が必要なカット: {', '.join(summary['needs_shoot']) or 'なし'}",
              f"- WARN: {len(warns)} 件"]
    lines += [f"  - {w}" for w in warns]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="storyboard.json を検算し、Markdown / CSV に書き出す")
    ap.add_argument("json_path", help="storyboard.json")
    ap.add_argument("--md", default="", help="編集依頼書を Markdown で書き出す先")
    ap.add_argument("--csv", default="", help="カット表を CSV で書き出す先（表計算ソフトに貼る用）")
    ap.add_argument("--narration-cps", type=float, default=5.0, help="ナレーションの上限（文字/秒。既定 5）")
    ap.add_argument("--telop-cps", type=float, default=4.0, help="テロップの上限（文字/秒。既定 4）")
    args = ap.parse_args()

    try:
        sb = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
        warns, summary = validate(sb, args.narration_cps, args.telop_cps)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    for w in warns:
        print(f"WARN: {w}")
    print(json.dumps(summary, ensure_ascii=False))

    if args.md:
        path = Path(args.md)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_md(sb, summary, warns), encoding="utf-8")
        print(f"OK: {path}")
    if args.csv:
        path = Path(args.csv)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(HEADER)
            for c in sb.get("cuts", []):
                writer.writerow([cell(c.get(k)) for k in KEYS])
        print(f"OK: {path}")
    return 2 if warns else 0


if __name__ == "__main__":
    sys.exit(main())
