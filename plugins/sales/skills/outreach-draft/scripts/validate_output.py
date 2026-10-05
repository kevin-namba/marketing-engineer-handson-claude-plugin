#!/usr/bin/env python3
"""一括生成した営業文面の CSV を、人に渡す前に検査する。

標準ライブラリだけで動く。検査するのは形式と整合だけで、事実の正しさ（本文の言及がリサーチメモにあるか・
実績が承認済みリストにあるか）は別に確かめる。--approved を渡すと、evidence_case がリストに含まれるかも照合する。

  python3 validate_output.py --in outreach.csv
  python3 validate_output.py --in outreach.csv --approved approved_cases.txt --json

終了コード: 問題なし 0 / 問題あり 1 / 入力の誤り 2
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys

REQUIRED = [
    "company_name", "channel", "body", "opening_hook", "evidence_case", "cta",
    "personalization_source", "confidence", "needs_review", "notes",
]
MARKUP = [
    (re.compile(r"\*\*[^*\n]+\*\*"), "太字の記法"),
    (re.compile(r"(?m)^#{1,6}\s"), "見出しの記法"),
    (re.compile(r"(?m)^\s*[*+]\s"), "箇条書きの記法（* / +）"),
    (re.compile(r"\[[^\]\n]+\]\([^)\n]+\)"), "リンクの記法"),
    (re.compile(r"`[^`\n]+`"), "コードの記法"),
]
PLACEHOLDER = re.compile(r"\{\{[^}]*\}\}|［[^］]*］|｛｛[^｝]*｝｝|\[(?:会社名|氏名|名前|宛名|担当者)[^\]]*\]")
STOCK_OPENINGS = ["お世話になっております", "貴社ますます", "ますますご清栄", "ご連絡させていただいたのは"]
FAKE_PERSONAL = ["にお勤めとのことで"]


def truthy(value: str) -> bool:
    return (value or "").strip().lower() in {"true", "1", "yes", "y"}


def main() -> int:
    parser = argparse.ArgumentParser(description="一括生成した営業文面の CSV を検査する。")
    parser.add_argument("--in", dest="infile", required=True, help="出力 CSV（1 行 1 社）")
    parser.add_argument("--approved", help="承認済みの実績リスト（1 行 1 件のテキスト）。evidence_case を照合する")
    parser.add_argument("--max-chars", type=int, default=0, help="本文の文字数の上限（0 は検査しない）")
    parser.add_argument("--json", action="store_true", help="結果を JSON で出す")
    args = parser.parse_args()

    try:
        with open(args.infile, newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or [])
            rows = [dict(row) for row in reader]
    except OSError as error:
        print(f"読めません: {error}", file=sys.stderr)
        return 2

    approved: list[str] = []
    if args.approved:
        with open(args.approved, encoding="utf-8") as handle:
            approved = [line.strip() for line in handle if line.strip() and not line.startswith("#")]

    problems: list[dict[str, str]] = []

    def add(line: int, company: str, message: str) -> None:
        problems.append({"row": str(line), "company_name": company, "problem": message})

    missing = [name for name in REQUIRED if name not in fields]
    if missing:
        add(0, "", f"必須の列がありません: {', '.join(missing)}")
    has_subject = "subject" in fields

    bodies: dict[str, int] = {}
    review_rows = 0
    for index, row in enumerate(rows, start=2):  # 1 行目は見出し
        company = (row.get("company_name") or "").strip()
        body = row.get("body") or ""
        channel = (row.get("channel") or "").strip().lower()
        source = (row.get("personalization_source") or "").strip()
        review = truthy(row.get("needs_review", ""))
        review_rows += 1 if review else 0

        if not company:
            add(index, company, "company_name が空")
        if channel not in {"form", "email"}:
            add(index, company, f"channel が form / email のどちらでもない: {channel or '（空）'}")
        if not body.strip():
            add(index, company, "body が空")
            continue
        for pattern, label in MARKUP:
            if pattern.search(body):
                add(index, company, f"本文に{label}がある（プレーンテキストにする）")
        if PLACEHOLDER.search(body):
            add(index, company, "本文に埋められていない差し込みの箇所が残っている")
        head = body.strip()[:60]
        for phrase in STOCK_OPENINGS:
            if phrase in head:
                add(index, company, f"定型の挨拶で始まっている: {phrase}")
        for phrase in FAKE_PERSONAL:
            if phrase in body:
                add(index, company, f"見せかけのパーソナライズ: {phrase}")
        if has_subject:
            subject = (row.get("subject") or "").strip()
            if channel == "form" and subject:
                add(index, company, "form の行に subject が入っている（空にする）")
            if channel == "email" and not subject:
                add(index, company, "email の行に subject が無い")
        if not source:
            add(index, company, "personalization_source が空（根拠の入力列か generic を書く）")
        if source.lower() == "generic" and not review:
            add(index, company, "汎用の書き出し（generic）なのに needs_review が true でない")
        if (row.get("confidence") or "").strip() not in {"高", "中", "低"}:
            add(index, company, "confidence が 高 / 中 / 低 のどれでもない")
        if (row.get("confidence") or "").strip() == "低" and not review:
            add(index, company, "confidence が低なのに needs_review が true でない")
        evidence = (row.get("evidence_case") or "").strip()
        if approved and evidence and not any(evidence in item or item in evidence for item in approved):
            add(index, company, f"evidence_case が承認済みリストに見つからない: {evidence}")
        if args.max_chars and len(body) > args.max_chars:
            add(index, company, f"本文が {len(body)} 文字（上限 {args.max_chars}）")
        key = re.sub(r"\s+", "", body)
        if key in bodies:
            add(index, company, f"本文が {bodies[key]} 行目と同一（1 行 1 社で書き分ける）")
        else:
            bodies[key] = index

    result = {
        "rows": len(rows),
        "needs_review_rows": review_rows,
        "problem_count": len(problems),
        "problems": problems,
        "note": "形式と整合の検査だけ。本文の事実がリサーチメモにあるかは別に確かめる。",
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{len(rows)} 行 / 要レビュー {review_rows} 行 / 問題 {len(problems)} 件")
        for item in problems:
            where = f"{item['row']} 行目" if item["row"] != "0" else "全体"
            name = f"（{item['company_name']}）" if item["company_name"] else ""
            print(f"- {where}{name}: {item['problem']}")
        print(result["note"])
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
