#!/usr/bin/env python3
"""A/B テストを始める前に、1 つの案に必要な訪問数と日数を計算する。

標準ライブラリだけで動く（2 つの割合の差を見分けるための、一般的な近似式）。

使い方::

    # いまの申し込み率 2% が 2.5% になる差を見分けたい。1 日の訪問は 180 件、案は 2 つ
    python3 sample_size.py --baseline 0.02 --target 0.025 --daily-visits 180 --variants 2

    # 割合は % でも渡せる
    python3 sample_size.py --baseline 2% --target 2.5% --daily-visits 180

出力は JSON。日数は 1 週間単位に切り上げる（曜日によって来る人が違うため）。
計算は目安。判定は、始める前に決めた期間と基準で行う。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from statistics import NormalDist


def parse_rate(text: str) -> float:
    raw = text.strip()
    value = float(raw.rstrip("%")) / 100 if raw.endswith("%") else float(raw)
    if not 0 < value < 1:
        raise ValueError(f"割合は 0 と 1 の間（または 0%〜100%）で渡す: {text}")
    return value


def per_variant(p1: float, p2: float, alpha: float, power: float) -> int:
    z_a = NormalDist().inv_cdf(1 - alpha / 2)
    z_b = NormalDist().inv_cdf(power)
    p_bar = (p1 + p2) / 2
    num = (z_a * math.sqrt(2 * p_bar * (1 - p_bar)) + z_b * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2
    return math.ceil(num / (p2 - p1) ** 2)


def main() -> int:
    ap = argparse.ArgumentParser(description="A/B テストに必要な訪問数と日数を計算する")
    ap.add_argument("--baseline", required=True, help="いまの割合（例: 0.02 または 2%%）。申し込み率やマイクロ CV の率")
    ap.add_argument("--target", required=True, help="見分けたい割合（例: 0.025 または 2.5%%）")
    ap.add_argument("--daily-visits", type=float, default=0, help="LP 全体の 1 日の訪問数（日数の計算に使う）")
    ap.add_argument("--variants", type=int, default=2, help="同時に比べる案の数（元の案を含む。既定 2）")
    ap.add_argument("--alpha", type=float, default=0.05, help="偶然の差を「差がある」と読む確率の上限（既定 0.05）")
    ap.add_argument("--power", type=float, default=0.8, help="本当の差を見つけられる確率（既定 0.8）")
    args = ap.parse_args()

    try:
        p1, p2 = parse_rate(args.baseline), parse_rate(args.target)
        if p1 == p2:
            raise ValueError("--baseline と --target が同じ値です")
        if args.variants < 2:
            raise ValueError("--variants は 2 以上にする")
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    n = per_variant(p1, p2, args.alpha, args.power)
    result: dict[str, object] = {
        "baseline": p1,
        "target": p2,
        "relative_change": round((p2 - p1) / p1, 4),
        "visits_per_variant": n,
        "visits_total": n * args.variants,
        "expected_conversions_per_variant": {"baseline": round(n * p1, 1), "target": round(n * p2, 1)},
        "notes": [
            "計算は目安。判定は、始める前に決めた期間と基準で行う",
            "判定に使う成果がどちらかの案で 50 件に満たなければ、勝ち負けを決めない",
        ],
    }
    if args.daily_visits > 0:
        days = math.ceil(n * args.variants / args.daily_visits)
        weeks = max(1, math.ceil(days / 7))
        result["days_raw"] = days
        result["weeks"] = weeks
        result["days"] = weeks * 7
        if weeks > 8:
            result["notes"].append(  # type: ignore[union-attr]
                "8 週間を超える。最終的な成果の手前で必ず起きる行動（マイクロ CV。フォームの入力開始など）で判定するか、見分けたい差を大きくする"
            )
    if min(n * p1, n * p2) < 50:
        result["notes"].append("計算上の件数が 50 件に満たない。期間を延ばして 50 件に届く日数を取る")  # type: ignore[union-attr]

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
