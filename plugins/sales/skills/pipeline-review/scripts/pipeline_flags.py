#!/usr/bin/env python3
"""開いている商談の一覧（CSV）に、固定の閾値でリスクフラグと優先順位を付ける。

判定は決定的（同じ入力と同じ基準日から同じ結果が出る）。生成 AI は使わない。
標準ライブラリだけで動く。

入力 CSV の列（見出しは英語名か日本語の別名のどちらでもよい。無い列は「未取得」として扱う）:
  name             案件名 / 企業名
  status           ステータス
  amount           金額（月額。円。数字以外の文字は取り除く）
  term_months      契約期間（月数）
  target_month     成約予定 / 獲得目標月（YYYY-MM か YYYY-MM-DD か YYYY/MM）
  owner            担当者
  next_action      次アクション / ネクストアクション
  channel          チャネル / 流入元
  updated_at       最終更新日（YYYY-MM-DD）
  stage_entered_at ステータス変更日（YYYY-MM-DD）
  contacts         相手側の連絡先の数
  postponed_count  先送り回数
  last_response_at 最終反応日（YYYY-MM-DD）

使い方:
  python3 pipeline_flags.py --deals deals.csv
  python3 pipeline_flags.py --deals deals.csv --today 2026-10-05 --format json
  python3 pipeline_flags.py --deals deals.csv --thresholds my-thresholds.json --statuses statuses.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

DEFAULT_THRESHOLDS = Path(__file__).resolve().parent.parent / "references" / "thresholds.json"

ALIASES = {
    "name": ["name", "案件名", "企業名", "会社名", "クライアント名", "商談名"],
    "status": ["status", "ステータス", "ステージ"],
    "amount": ["amount", "monthly_amount", "金額", "月額"],
    "term_months": ["term_months", "契約期間", "期間"],
    "target_month": ["target_month", "close_date", "成約予定", "獲得目標月", "成約予定日"],
    "owner": ["owner", "担当者"],
    "next_action": ["next_action", "次アクション", "ネクストアクション"],
    "channel": ["channel", "チャネル", "流入元"],
    "updated_at": ["updated_at", "最終更新日", "最終更新", "最終活動日"],
    "stage_entered_at": ["stage_entered_at", "ステータス変更日", "ステージ変更日"],
    "contacts": ["contacts", "連絡先の数", "連絡先数", "相手側の連絡先の数"],
    "postponed_count": ["postponed_count", "先送り回数"],
    "last_response_at": ["last_response_at", "最終反応日"],
}

HYGIENE_FIELDS = [
    ("next_action", "次アクション"),
    ("target_month", "期日"),
    ("amount", "金額"),
    ("owner", "担当者"),
    ("channel", "チャネル"),
]


def parse_date(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S", "%Y年%m月%d日"):
        try:
            return datetime.strptime(value[:19] if "T" in value else value, fmt).date()
        except ValueError:
            continue
    return None


def parse_month(value: str) -> date | None:
    """成約予定を月の初日に直す。読めなければ None（推測で埋めない）。"""
    value = (value or "").strip()
    if not value:
        return None
    m = re.match(r"^(\d{4})[-/年](\d{1,2})", value)
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        return None
    return date(year, month, 1)


def parse_number(value: str) -> float | None:
    value = (value or "").strip()
    if not value:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", value)
    if cleaned in ("", "-", "."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def load_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        mapping: dict[str, str] = {}
        for key, names in ALIASES.items():
            for h in headers:
                if h and h.strip() in names:
                    mapping[key] = h
                    break
        if "name" not in mapping or "status" not in mapping:
            sys.exit(
                "エラー: 案件名（name）とステータス（status）の列が必要です。"
                f" 見つかった見出し: {headers}"
            )
        rows = []
        for raw in reader:
            row = {key: (raw.get(col) or "").strip() for key, col in mapping.items()}
            row["_missing_columns"] = [k for k in ALIASES if k not in mapping]
            rows.append(row)
        return rows


def load_statuses(path: Path | None) -> dict[str, dict]:
    """ステータス表（SSOT）。{label or id: {probability, open}}。"""
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("statuses", data) if isinstance(data, dict) else data
    table: dict[str, dict] = {}
    for it in items:
        entry = {"probability": float(it.get("probability", 0)), "open": bool(it.get("open", True))}
        for key in (it.get("id"), it.get("label")):
            if key:
                table[str(key)] = entry
    return table


def months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def analyse(rows: list[dict], today: date, cfg: dict, statuses: dict[str, dict]) -> dict:
    closed_labels = set(cfg.get("closed_statuses", []))
    month_start = today.replace(day=1)
    deals = []
    skipped_closed = 0
    for row in rows:
        status = row.get("status", "")
        st = statuses.get(status)
        is_open = st["open"] if st else status not in closed_labels
        if not is_open:
            skipped_closed += 1
            continue

        amount = parse_number(row.get("amount", ""))
        updated = parse_date(row.get("updated_at", ""))
        stage_in = parse_date(row.get("stage_entered_at", ""))
        target = parse_month(row.get("target_month", ""))
        contacts = parse_number(row.get("contacts", ""))
        postponed = parse_number(row.get("postponed_count", ""))
        last_resp = parse_date(row.get("last_response_at", "")) or updated

        idle_days = (today - updated).days if updated else None
        stage_days = (today - stage_in).days if stage_in else None
        silent_days = (today - last_resp).days if last_resp else None

        flags: list[str] = []
        unknown: list[str] = []
        if idle_days is None:
            unknown.append("停滞（最終更新日が未取得）")
        elif idle_days >= cfg["idle_days"]:
            flags.append("停滞")
        if stage_days is None:
            unknown.append("行き詰まり（ステータス変更日が未取得）")
        elif stage_days >= cfg["stuck_days"]:
            flags.append("行き詰まり")
        if target is not None and target < month_start:
            flags.append("期日超過")
        if contacts is None:
            unknown.append("単線（連絡先の数が未取得）")
        elif contacts <= cfg["single_thread_contacts"]:
            flags.append("単線")
        empty = [label for key, label in HYGIENE_FIELDS if key not in row["_missing_columns"] and not row.get(key, "")]
        if empty:
            flags.append("衛生")

        prune_reasons = []
        if silent_days is not None and silent_days >= cfg["prune_silent_days"]:
            prune_reasons.append(f"{silent_days} 日反応なし")
        if postponed is not None and postponed >= cfg["prune_postponed_count"]:
            prune_reasons.append(f"{int(postponed)} 回先送り")

        deals.append(
            {
                "name": row.get("name", ""),
                "status": status,
                "amount": amount,
                "target_month": target.strftime("%Y-%m") if target else None,
                "owner": row.get("owner", "") or None,
                "next_action": row.get("next_action", "") or None,
                "channel": row.get("channel", "") or None,
                "idle_days": idle_days,
                "stage_days": stage_days,
                "contacts": int(contacts) if contacts is not None else None,
                "flags": flags,
                "unknown": unknown,
                "empty_fields": empty,
                "prune_reasons": prune_reasons,
                "_target": target,
                "_prob": st["probability"] if st else None,
            }
        )

    # 優先順位（重みは設定から読む。各要素は 0〜1 に換算する）
    weights = cfg["weights"]
    amounts = [d["amount"] for d in deals if d["amount"]]
    max_amount = max(amounts) if amounts else None
    order = cfg.get("status_order", [])
    for d in deals:
        parts = {}
        if d["_target"] is None:
            parts["closeness"] = 0.0
        else:
            diff = months_between(month_start, d["_target"])
            parts["closeness"] = 1.0 if diff <= 0 else 0.7 if diff == 1 else 0.4 if diff <= 3 else 0.1
        parts["size"] = (d["amount"] / max_amount) if (d["amount"] and max_amount) else 0.0
        if d["_prob"] is not None:
            parts["stage"] = d["_prob"] / 100.0
        elif d["status"] in order and len(order) > 1:
            parts["stage"] = order.index(d["status"]) / (len(order) - 1)
        else:
            parts["stage"] = 0.0
        if d["idle_days"] is None:
            parts["activity"] = 0.0
        else:
            half = max(cfg["idle_days"] // 2, 1)
            parts["activity"] = 1.0 if d["idle_days"] <= half else 0.5 if d["idle_days"] < cfg["idle_days"] else 0.0
        parts["risk"] = 1.0 - min(len(d["flags"]), 5) / 5.0
        d["score"] = round(sum(weights[k] * parts[k] for k in weights), 1)
        d["score_parts"] = {k: round(v, 2) for k, v in parts.items()}
        del d["_target"], d["_prob"]

    deals.sort(key=lambda d: (-d["score"], d["name"]))

    total = len(deals)

    def health(flag: str, unknown_key: str) -> dict:
        hit = sum(1 for d in deals if flag in d["flags"])
        unk = sum(1 for d in deals if any(u.startswith(unknown_key) for u in d["unknown"]))
        return {"flagged": hit, "unknown": unk}

    shape_stage: dict[str, dict] = {}
    shape_month: dict[str, dict] = {}
    shape_size: dict[str, dict] = {}
    bands = cfg.get("size_bands", [])
    for d in deals:
        for bucket, key in ((shape_stage, d["status"] or "（空）"), (shape_month, d["target_month"] or "未設定")):
            b = bucket.setdefault(key, {"count": 0, "amount": 0.0, "amount_missing": 0})
            b["count"] += 1
            if d["amount"] is None:
                b["amount_missing"] += 1
            else:
                b["amount"] += d["amount"]
        if d["amount"] is None:
            label = "金額が空"
        else:
            label = next((bd["label"] for bd in bands if d["amount"] >= bd["min"]), "区分なし") if bands else "区分なし"
        b = shape_size.setdefault(label, {"count": 0, "amount": 0.0, "amount_missing": 0})
        b["count"] += 1
        if d["amount"] is not None:
            b["amount"] += d["amount"]
        else:
            b["amount_missing"] += 1

    hygiene: dict[str, int] = {}
    for d in deals:
        for label in d["empty_fields"]:
            hygiene[label] = hygiene.get(label, 0) + 1

    return {
        "today": today.isoformat(),
        "thresholds": {k: cfg[k] for k in ("idle_days", "stuck_days", "single_thread_contacts", "prune_silent_days", "prune_postponed_count")},
        "weights": weights,
        "open_deals": total,
        "excluded_closed": skipped_closed,
        "missing_columns": rows[0]["_missing_columns"] if rows else [],
        "health": {
            "ステージの進み具合（行き詰まり）": health("行き詰まり", "行き詰まり"),
            "活動の新しさ（停滞）": health("停滞", "停滞"),
            "期日の正確さ（期日超過）": {"flagged": sum(1 for d in deals if "期日超過" in d["flags"]), "unknown": sum(1 for d in deals if d["target_month"] is None)},
            "連絡先の数（単線）": health("単線", "単線"),
        },
        "top": deals[: cfg.get("focus_count", 5)],
        "deals": deals,
        "prune_candidates": [d for d in deals if d["prune_reasons"]],
        "hygiene": hygiene,
        "shape": {"stage": shape_stage, "target_month": shape_month, "size": shape_size},
    }


def yen(v: float | None) -> str:
    return "未取得" if v is None else f"¥{v:,.0f}"


def days(v: int | None) -> str:
    return "未取得" if v is None else f"{v} 日"


def to_markdown(r: dict) -> str:
    out = [f"# パイプラインのフラグ判定（基準日 {r['today']}）", ""]
    t = r["thresholds"]
    out.append(
        f"閾値: 停滞 {t['idle_days']} 日 / 行き詰まり {t['stuck_days']} 日 / 単線 連絡先 {t['single_thread_contacts']} 人以下 / "
        f"削除候補 {t['prune_silent_days']} 日反応なし または {t['prune_postponed_count']} 回先送り"
    )
    out.append(f"開いている商談: {r['open_deals']} 件（締結・失注・保留として除外: {r['excluded_closed']} 件）")
    if r["missing_columns"]:
        out.append(f"入力に無かった列（該当する判定は「未取得」）: {', '.join(r['missing_columns'])}")
    out += ["", "## 4 つの観点", "", "| 観点 | 該当 | 判定できず（未取得） |", "|---|---|---|"]
    for k, v in r["health"].items():
        out.append(f"| {k} | {v['flagged']} 件 | {v['unknown']} 件 |")
    out += ["", "## 優先順位（スコア順）", "", "| # | 案件名 | ステータス | 金額 | 成約予定 | 更新なし | 同一ステータス | フラグ | スコア |", "|---|---|---|---|---|---|---|---|---|"]
    for i, d in enumerate(r["deals"], 1):
        out.append(
            f"| {i} | {d['name']} | {d['status']} | {yen(d['amount'])} | {d['target_month'] or '未設定'} | "
            f"{days(d['idle_days'])} | {days(d['stage_days'])} | {'・'.join(d['flags']) or '-'} | {d['score']} |"
        )
    out += ["", "## 削除候補", ""]
    if r["prune_candidates"]:
        out += ["| 案件名 | ステータス | 金額 | 理由 |", "|---|---|---|---|"]
        for d in r["prune_candidates"]:
            out.append(f"| {d['name']} | {d['status']} | {yen(d['amount'])} | {' / '.join(d['prune_reasons'])} |")
    else:
        out.append("該当なし")
    out += ["", "## データの欠け", ""]
    if r["hygiene"]:
        out += ["| 空欄の項目 | 件数 | 案件 |", "|---|---|---|"]
        for label, n in r["hygiene"].items():
            names = [d["name"] for d in r["deals"] if label in d["empty_fields"]]
            out.append(f"| {label} | {n} | {'、'.join(names)} |")
    else:
        out.append("空欄なし")
    for title, key in (("ステージ別", "stage"), ("成約月別", "target_month"), ("規模別", "size")):
        out += ["", f"## 形状: {title}", "", "| 区分 | 件数 | 金額の合計 | 金額が空 |", "|---|---|---|---|"]
        for label, b in sorted(r["shape"][key].items()):
            out.append(f"| {label} | {b['count']} | ¥{b['amount']:,.0f} | {b['amount_missing']} 件 |")
    return "\n".join(out) + "\n"


def main() -> None:
    p = argparse.ArgumentParser(description="開いている商談に固定の閾値でフラグと優先順位を付ける（決定的・生成 AI 不使用）")
    p.add_argument("--deals", required=True, help="商談一覧の CSV（UTF-8）")
    p.add_argument("--thresholds", default=str(DEFAULT_THRESHOLDS), help="閾値と重みの JSON（既定: references/thresholds.json）")
    p.add_argument("--statuses", help="ステータス表の JSON（id / label / probability / open）。あればステージの換算と対象の絞り込みに使う")
    p.add_argument("--today", help="基準日 YYYY-MM-DD（既定: 今日）")
    p.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = p.parse_args()

    cfg = json.loads(Path(args.thresholds).expanduser().read_text(encoding="utf-8"))
    today = parse_date(args.today) if args.today else date.today()
    if today is None:
        sys.exit("エラー: --today は YYYY-MM-DD で指定してください")
    statuses = load_statuses(Path(args.statuses).expanduser()) if args.statuses else {}
    rows = load_rows(Path(args.deals).expanduser())
    result = analyse(rows, today, cfg, statuses)
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(to_markdown(result))


if __name__ == "__main__":
    main()
