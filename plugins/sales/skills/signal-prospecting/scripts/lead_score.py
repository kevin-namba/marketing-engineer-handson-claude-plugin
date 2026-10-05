#!/usr/bin/env python3
"""重みの設定（JSON）から、足し算だけでリードスコアを出す。内訳を添える。

標準ライブラリだけで動く。同じ入力からは必ず同じ結果が出る（生成 AI は使わない）。

  python3 lead_score.py --leads leads.csv --weights weights.json --out scored.csv
  python3 lead_score.py --leads leads.csv --weights weights.json --today 2026-10-04

重みの JSON の形は references/lead-scoring.md を参照。
値が空の列には加点せず、内訳に「未取得」と出す（0 として扱わない）。
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys

TRUTHY = {"1", "true", "yes", "y", "あり", "有", "○", "◯", "済"}


def to_number(value: str) -> float | None:
    text = (value or "").replace(",", "").replace("%", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_date(value: str) -> dt.date | None:
    text = (value or "").strip()[:10].replace("/", "-")
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        return None


def matches(rule: dict, raw: str) -> bool | None:
    """True / False を返す。値が空で判定できないときは None。"""
    value = (raw or "").strip()
    op = rule.get("op", "eq")
    if value == "":
        return None
    if op == "eq":
        return value == str(rule.get("value", ""))
    if op == "in":
        return value in [str(item) for item in rule.get("value", [])]
    if op == "contains":
        return str(rule.get("value", "")) in value
    if op == "truthy":
        return value.lower() in TRUTHY
    number = to_number(value)
    if number is None:
        return None
    if op == "between":
        low, high = rule.get("value", [None, None])
        return float(low) <= number <= float(high)
    if op == "gte":
        return number >= float(rule.get("value"))
    if op == "lte":
        return number <= float(rule.get("value"))
    raise ValueError(f"未対応の op です: {op}")


def score_row(row: dict[str, str], config: dict, today: dt.date) -> tuple[float, list[str], list[str]]:
    total = 0.0
    breakdown: list[str] = []
    missing: list[str] = []
    expire_days = config.get("signal_expire_days")
    observed = parse_date(row.get("observed_at", ""))
    for rule in config.get("rules", []):
        column = rule["column"]
        label = rule.get("label", column)
        group = rule.get("group", "")
        if group == "signal" and expire_days is not None:
            if observed is None:
                if f"observed_at（{label}）" not in missing:
                    missing.append(f"observed_at（{label}）")
                continue
            if (today - observed).days > int(expire_days):
                continue
        result = matches(rule, row.get(column, ""))
        if result is None:
            if column not in missing:
                missing.append(column)
            continue
        if result:
            points = float(rule.get("points", 0))
            total += points
            breakdown.append(f"{group}:{label} +{points:g}")
    return total, breakdown, missing


def main() -> int:
    parser = argparse.ArgumentParser(
        description="重みの設定（JSON）から、足し算だけでリードスコアを出す。内訳を添える。")
    parser.add_argument("--leads", required=True, help="リード一覧（CSV。1 行 1 社）")
    parser.add_argument("--weights", required=True, help="重みの設定（JSON）")
    parser.add_argument("--out", help="結果の CSV。省略すると標準出力")
    parser.add_argument("--today", help="経過日数の基準日（YYYY-MM-DD）。省略すると実行日")
    args = parser.parse_args()

    with open(args.weights, encoding="utf-8") as handle:
        config = json.load(handle)
    today = parse_date(args.today) if args.today else dt.date.today()
    if today is None:
        print("--today は YYYY-MM-DD で指定してください", file=sys.stderr)
        return 2
    threshold = config.get("handoff_threshold")

    with open(args.leads, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]

    scored = []
    for index, row in enumerate(rows):
        total, breakdown, missing = score_row(row, config, today)
        row["score"] = f"{total:g}"
        row["score_breakdown"] = " / ".join(breakdown) if breakdown else "加点なし"
        row["score_missing"] = "未取得: " + ", ".join(missing) if missing else ""
        if threshold is None:
            row["handoff"] = ""
        else:
            row["handoff"] = "営業に渡す" if total >= float(threshold) else "育成"
        scored.append((-total, index, row))
    scored.sort(key=lambda item: (item[0], item[1]))

    extra = ["score", "handoff", "score_breakdown", "score_missing"]
    out_fields = extra + [name for name in fields if name not in extra]
    target = open(args.out, "w", newline="", encoding="utf-8") if args.out else sys.stdout
    try:
        writer = csv.DictWriter(target, fieldnames=out_fields, extrasaction="ignore")
        writer.writeheader()
        for _, _, row in scored:
            writer.writerow(row)
    finally:
        if args.out:
            target.close()

    handed = sum(1 for _, _, row in scored if row["handoff"] == "営業に渡す")
    print(f"{len(scored)} 行を採点（基準日 {today.isoformat()}）。閾値以上 {handed} 行。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
