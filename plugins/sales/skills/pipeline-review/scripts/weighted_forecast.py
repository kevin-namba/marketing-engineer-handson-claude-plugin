#!/usr/bin/env python3
"""加重フォーキャストを決定的に計算する（標準ライブラリだけで動く）。

  案件価値 = 月額 × 契約期間
  加重値   = 案件価値 × ステータス表の確度
  ベスト   = 締結済み + 対象の開いている案件の全件
  想定     = 締結済み + 加重値の合計
  ワースト = 締結済み + コミット案件だけ
  カバレッジ = 対象の開いている案件の合計 ÷ 目標

確度はこのスクリプトの中に持たない。必ず --statuses（ステータス表の SSOT）から読む。
金額・契約期間・成約予定が空の案件と、成約予定を過ぎた案件は計算に入れず、件数と一覧を出力に書く。

入力 CSV の列（見出しは英語名か日本語の別名）:
  name / 案件名, status / ステータス, amount / 月額 / 金額, term_months / 契約期間,
  target_month / 成約予定 / 獲得目標月, commit / コミット（任意。yes・no。人が付けた判断を優先する）

使い方:
  python3 weighted_forecast.py --deals deals.csv --statuses statuses.json \
      --period 2026-10:2026-12 --target 6000000 --closed 1200000
  python3 weighted_forecast.py ... --save-dir ~/forecasts            # 今回の予測を日付付きで保存
  python3 weighted_forecast.py ... --previous ~/forecasts/forecast-2026-07-01.json --actual 4100000
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

ALIASES = {
    "name": ["name", "案件名", "企業名", "会社名", "クライアント名", "商談名"],
    "status": ["status", "ステータス", "ステージ"],
    "amount": ["amount", "monthly_amount", "月額", "金額"],
    "term_months": ["term_months", "契約期間", "期間"],
    "target_month": ["target_month", "close_date", "成約予定", "獲得目標月", "成約予定日"],
    "commit": ["commit", "コミット"],
}


def parse_month(value: str) -> date | None:
    m = re.match(r"^(\d{4})[-/年](\d{1,2})", (value or "").strip())
    if not m or not 1 <= int(m.group(2)) <= 12:
        return None
    return date(int(m.group(1)), int(m.group(2)), 1)


def parse_number(value: str) -> float | None:
    cleaned = re.sub(r"[^\d.\-]", "", (value or "").strip())
    if cleaned in ("", "-", "."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def load_statuses(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("statuses", data) if isinstance(data, dict) else data
    table: dict[str, dict] = {}
    for it in items:
        if "probability" not in it:
            sys.exit(f"エラー: ステータス表の {it} に probability がありません")
        entry = {
            "label": it.get("label") or it.get("id"),
            "probability": float(it["probability"]),
            "open": bool(it.get("open", True)),
        }
        for key in (it.get("id"), it.get("label")):
            if key:
                table[str(key)] = entry
    return table


def load_deals(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        mapping = {}
        for key, names in ALIASES.items():
            for h in headers:
                if h and h.strip() in names:
                    mapping[key] = h
                    break
        for required in ("name", "status", "amount", "term_months", "target_month"):
            if required not in mapping:
                sys.exit(f"エラー: 必須の列 {required}（{' / '.join(ALIASES[required])}）がありません。見出し: {headers}")
        return [{k: (raw.get(col) or "").strip() for k, col in mapping.items()} for raw in reader]


def compute(deals, statuses, start, end, today, target, closed, commit_min):
    month_start = today.replace(day=1)
    included, excluded = [], {"締結・失注・保留": [], "ステータスが表に無い": [], "金額か契約期間が空": [], "成約予定が空": [], "成約予定を過ぎている": [], "期間の外": []}
    for d in deals:
        st = statuses.get(d["status"])
        if st is None:
            excluded["ステータスが表に無い"].append(d["name"])
            continue
        if not st["open"]:
            excluded["締結・失注・保留"].append(d["name"])
            continue
        amount, term = parse_number(d["amount"]), parse_number(d["term_months"])
        if amount is None or term is None:
            excluded["金額か契約期間が空"].append(d["name"])
            continue
        tm = parse_month(d["target_month"])
        if tm is None:
            excluded["成約予定が空"].append(d["name"])
            continue
        if tm < month_start:
            excluded["成約予定を過ぎている"].append(d["name"])
            continue
        if tm < start or tm > end:
            excluded["期間の外"].append(d["name"])
            continue
        value = amount * term
        mark = d.get("commit", "").lower()
        if mark in ("yes", "y", "true", "1", "○", "はい"):
            commit = True
        elif mark in ("no", "n", "false", "0", "×", "いいえ"):
            commit = False
        else:
            commit = st["probability"] >= commit_min
        included.append(
            {
                "name": d["name"],
                "status": st["label"],
                "probability": st["probability"],
                "monthly_amount": amount,
                "term_months": term,
                "value": value,
                "weighted": round(value * st["probability"] / 100.0),
                "target_month": tm.strftime("%Y-%m"),
                "commit": commit,
                "commit_source": "人の判断" if mark else f"確度 {commit_min:g}% {'以上' if commit else '未満'}",
            }
        )

    open_total = sum(d["value"] for d in included)
    weighted_total = sum(d["weighted"] for d in included)
    commit_total = sum(d["value"] for d in included if d["commit"])
    by_stage: dict[str, dict] = {}
    for d in included:
        b = by_stage.setdefault(d["status"], {"count": 0, "value": 0.0, "probability": d["probability"], "weighted": 0.0})
        b["count"] += 1
        b["value"] += d["value"]
        b["weighted"] += d["weighted"]

    scenarios = {"best": closed + open_total, "expected": closed + weighted_total, "worst": closed + commit_total}
    result = {
        "generated_on": today.isoformat(),
        "period": {"start": start.strftime("%Y-%m"), "end": end.strftime("%Y-%m")},
        "target": target,
        "closed": closed,
        "open_total": open_total,
        "weighted_total": weighted_total,
        "commit_total": commit_total,
        "upside_total": open_total - commit_total,
        "scenarios": scenarios,
        "gap_to_target": None if target is None else target - scenarios["expected"],
        "coverage": None if not target else round(open_total / target, 2),
        "by_stage": by_stage,
        "commit": [d for d in included if d["commit"]],
        "upside": [d for d in included if not d["commit"]],
        "excluded": {k: v for k, v in excluded.items() if v},
    }
    return result


def yen(v) -> str:
    return "未設定" if v is None else f"¥{v:,.0f}"


def to_markdown(r: dict, prev: dict | None, actual: float | None) -> str:
    p = r["period"]
    out = [f"# 加重フォーキャスト: {p['start']} 〜 {p['end']}（計算日 {r['generated_on']}）", "", "## サマリー", "", "| 指標 | 値 |", "|---|---|"]
    out.append(f"| 目標 | {yen(r['target'])} |")
    out.append(f"| 締結済み | {yen(r['closed'])} |")
    out.append(f"| 開いている案件（対象） | {yen(r['open_total'])} |")
    out.append(f"| 加重値の合計 | {yen(r['weighted_total'])} |")
    out.append(f"| ギャップ（目標 − 想定） | {yen(r['gap_to_target'])} |")
    cov = r["coverage"]
    cov_text = "未設定（目標が無い）" if cov is None else f"{cov} 倍" + ("（警告: 2 倍未満）" if cov < 2 else "（目安の 3 倍に不足）" if cov < 3 else "")
    out.append(f"| カバレッジ | {cov_text} |")
    out += ["", "## 3 シナリオ", "", "| シナリオ | 金額 | 前提 |", "|---|---|---|"]
    s = r["scenarios"]
    out.append(f"| ベスト | {yen(s['best'])} | 対象の開いている案件が全件成約 |")
    out.append(f"| 想定 | {yen(s['expected'])} | 加重値の合計 |")
    out.append(f"| ワースト | {yen(s['worst'])} | コミット案件だけ成約 |")
    out += ["", "## ステージ別", "", "| ステータス | 件数 | 合計 | 確度 | 加重 |", "|---|---|---|---|---|"]
    for label, b in sorted(r["by_stage"].items(), key=lambda kv: -kv[1]["probability"]):
        out.append(f"| {label} | {b['count']} | {yen(b['value'])} | {b['probability']:g}% | {yen(b['weighted'])} |")
    for title, key in (("コミット", "commit"), ("アップサイド", "upside")):
        out += ["", f"## {title}", ""]
        if not r[key]:
            out.append("該当なし")
            continue
        out += ["| 案件名 | ステータス | 月額 × 期間 | 案件価値 | 加重 | 成約予定 | 区分の根拠 |", "|---|---|---|---|---|---|---|"]
        for d in r[key]:
            out.append(
                f"| {d['name']} | {d['status']} | {yen(d['monthly_amount'])} × {d['term_months']:g} | {yen(d['value'])} | "
                f"{yen(d['weighted'])} | {d['target_month']} | {d['commit_source']} |"
            )
    out += ["", "## 予測から外した案件", ""]
    if r["excluded"]:
        out += ["| 理由 | 件数 | 案件 |", "|---|---|---|"]
        for reason, names in r["excluded"].items():
            out.append(f"| {reason} | {len(names)} | {'、'.join(names)} |")
    else:
        out.append("なし")
    if prev:
        out += ["", "## 前回の予測との差", "", "| 項目 | 前回 | 今回 / 実績 |", "|---|---|---|"]
        ps = prev.get("scenarios", {})
        out.append(f"| 前回の計算日・期間 | {prev.get('generated_on')}・{prev.get('period', {}).get('start')} 〜 {prev.get('period', {}).get('end')} | - |")
        out.append(f"| 想定 | {yen(ps.get('expected'))} | {yen(s['expected'])} |")
        if actual is not None and ps.get("expected"):
            out.append(f"| 前回の想定に対する実績 | {yen(ps['expected'])} | {yen(actual)}（実績 ÷ 想定 = {actual / ps['expected']:.0%}） |")
            out.append(f"| 前回のシナリオの幅 | ワースト {yen(ps.get('worst'))} 〜 ベスト {yen(ps.get('best'))} | 実績は幅の{'中' if ps.get('worst', 0) <= actual <= ps.get('best', 0) else '外'} |")
        else:
            out.append("| 精度 | - | 未計測（前回の期間の実績を --actual で渡す） |")
    return "\n".join(out) + "\n"


def main() -> None:
    p = argparse.ArgumentParser(description="確度 × 単価 × 期間の加重フォーキャストを決定的に計算する")
    p.add_argument("--deals", required=True, help="商談一覧の CSV（UTF-8）")
    p.add_argument("--statuses", required=True, help="ステータス表の JSON（id / label / probability / open）。確度はここからだけ読む")
    p.add_argument("--period", required=True, help="対象期間 YYYY-MM:YYYY-MM（1 か月なら YYYY-MM）")
    p.add_argument("--target", type=float, help="期間の売上目標（円）")
    p.add_argument("--closed", type=float, default=0.0, help="期間内にすでに締結した額（円）")
    p.add_argument("--commit-min", type=float, default=90.0, help="commit 列が空の案件をコミットに入れる確度の下限（既定 90）")
    p.add_argument("--today", help="基準日 YYYY-MM-DD（既定: 今日）")
    p.add_argument("--save-dir", help="今回の予測を forecast-YYYY-MM-DD.json として保存するフォルダ（作業フォルダの外を指定する）")
    p.add_argument("--previous", help="前回保存した予測の JSON")
    p.add_argument("--actual", type=float, help="前回の期間の実績（円）。--previous と一緒に渡すと精度を出す")
    p.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = p.parse_args()

    parts = args.period.split(":")
    start, end = parse_month(parts[0]), parse_month(parts[-1])
    if start is None or end is None or end < start:
        sys.exit("エラー: --period は YYYY-MM:YYYY-MM で指定してください")
    today = datetime.strptime(args.today, "%Y-%m-%d").date() if args.today else date.today()
    statuses = load_statuses(Path(args.statuses).expanduser())
    deals = load_deals(Path(args.deals).expanduser())
    result = compute(deals, statuses, start, end, today, args.target, args.closed, args.commit_min)

    prev = json.loads(Path(args.previous).expanduser().read_text(encoding="utf-8")) if args.previous else None
    if args.save_dir:
        out_dir = Path(args.save_dir).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"forecast-{today.isoformat()}.json"
        n = 2
        while out_path.exists():  # 同じ日の予測を上書きしない
            out_path = out_dir / f"forecast-{today.isoformat()}-{n}.json"
            n += 1
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"保存: {out_path}", file=sys.stderr)
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(to_markdown(result, prev, args.actual))


if __name__ == "__main__":
    main()
