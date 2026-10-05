#!/usr/bin/env python3
"""前回と今回のリード一覧（CSV）を突き合わせ、新着に印を付ける。

標準ライブラリだけで動く。同じ入力からは必ず同じ結果が出る。

  python3 diff_leads.py --previous previous.csv --current current.csv --key url --out merged.csv
  python3 diff_leads.py --current current.csv --key company_name,domain   # 初回（前回なし）

キーに company_name を含めたときは、法人格の表記・全角半角・空白のゆれを揃えてから比べる。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata

CORP_WORDS = [
    "株式会社", "有限会社", "合同会社", "合資会社", "合名会社",
    "一般社団法人", "一般財団法人", "公益社団法人", "公益財団法人",
    "(株)", "(有)", "(同)", "㈱", "㈲",
]


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").strip().lower()
    for word in CORP_WORDS:
        text = text.replace(unicodedata.normalize("NFKC", word).lower(), "")
    return re.sub(r"[\s　・,.．，、。]+", "", text)


def normalize_domain(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").strip().lower()
    text = re.sub(r"^[a-z]+://", "", text)
    text = text.split("/")[0].split("?")[0]
    return re.sub(r"^www\.", "", text)


def normalize_url(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").strip()
    text = re.sub(r"#.*$", "", text)
    return text.rstrip("/").lower()


def normalize(column: str, value: str) -> str:
    name = column.lower()
    if name in ("company_name", "company", "法人名", "会社名"):
        return normalize_name(value)
    if name in ("domain", "ドメイン"):
        return normalize_domain(value)
    if name in ("url", "source_url", "出典url"):
        return normalize_url(value)
    return unicodedata.normalize("NFKC", value or "").strip().lower()


def read_rows(path: str) -> tuple[list[str], list[dict[str, str]]]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def key_of(row: dict[str, str], columns: list[str]) -> str:
    return "|".join(normalize(column, row.get(column, "")) for column in columns)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="前回と今回のリード一覧（CSV）を突き合わせ、新着に印を付ける。")
    parser.add_argument("--current", required=True, help="今回の一覧（CSV）")
    parser.add_argument("--previous", help="前回の一覧（CSV）。省略すると初回として扱う")
    parser.add_argument("--key", default="url",
                        help="突き合わせに使う列名。カンマ区切りで複数（例: company_name,domain）。既定は url")
    parser.add_argument("--out", help="結果の CSV。省略すると標準出力")
    parser.add_argument("--json", action="store_true", help="集計を JSON で標準エラー出力に出す")
    args = parser.parse_args()

    columns = [name.strip() for name in args.key.split(",") if name.strip()]
    fields, current = read_rows(args.current)
    missing = [name for name in columns if name not in fields]
    if missing:
        print(f"今回の一覧にキーの列がありません: {', '.join(missing)}", file=sys.stderr)
        return 2

    previous_keys: set[str] = set()
    first_run = args.previous is None
    if not first_run:
        prev_fields, previous = read_rows(args.previous)
        missing_prev = [name for name in columns if name not in prev_fields]
        if missing_prev:
            print(f"前回の一覧にキーの列がありません: {', '.join(missing_prev)}", file=sys.stderr)
            return 2
        previous_keys = {key_of(row, columns) for row in previous}

    seen: set[str] = set()
    fresh: list[dict[str, str]] = []
    carried: list[dict[str, str]] = []
    no_key = 0
    duplicates = 0
    for row in current:
        key = key_of(row, columns)
        if not key.replace("|", ""):
            row["lead_status"] = "キー未取得"
            no_key += 1
            fresh.append(row)
            continue
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        if first_run:
            row["lead_status"] = "初回"
            fresh.append(row)
        elif key in previous_keys:
            row["lead_status"] = "継続"
            carried.append(row)
        else:
            row["lead_status"] = "新着"
            fresh.append(row)

    out_fields = ["lead_status"] + [name for name in fields if name != "lead_status"]
    target = open(args.out, "w", newline="", encoding="utf-8") if args.out else sys.stdout
    try:
        writer = csv.DictWriter(target, fieldnames=out_fields, extrasaction="ignore")
        writer.writeheader()
        for row in fresh + carried:
            writer.writerow(row)
    finally:
        if args.out:
            target.close()

    summary = {
        "first_run": first_run,
        "new": sum(1 for row in fresh if row["lead_status"] == "新着"),
        "first": sum(1 for row in fresh if row["lead_status"] == "初回"),
        "carried": len(carried),
        "duplicates_dropped": duplicates,
        "missing_key": no_key,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False), file=sys.stderr)
    else:
        note = "初回なので突き合わせなし" if first_run else f"新着 {summary['new']} 件 / 継続 {summary['carried']} 件"
        print(f"{note} / 今回の一覧の中の重複 {duplicates} 件を除外 / キー未取得 {no_key} 件", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
