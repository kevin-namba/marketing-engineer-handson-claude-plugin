#!/usr/bin/env python3
"""巡回の判定スクリプト。

ルール（rules.json）と実績（metrics.json）を受け取り、操作を
「実行する / 提案する / 見送る」に分けて JSON で返す。標準ライブラリだけで動く。

同じ数字からは必ず同じ結果を返す（判定を AI に考えさせないためのスクリプト）。

使い方:
  python3 judge.py check  --rules rules.json
  python3 judge.py judge  --rules rules.json --metrics metrics.json [--log patrol-log.jsonl] [--now 2026-10-05T09:00:00+09:00]
  python3 judge.py record --log patrol-log.jsonl --rule "ルール名" --target-id ID --action "停止する" --result "実行した" [--detail "..."]

結果は標準出力に JSON で出す。ルールや実績の読み込みに失敗したときは
{"status": "error", "errors": [...]} を出して終了コード 1 で終わる
（このときは何も実行しない）。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------
# 媒体でできること（執筆時点。使う前に公式ドキュメントで確かめる）
# --------------------------------------------------------------------------

MEDIA: dict[str, dict[str, Any]] = {
    "Meta": {
        "levels": {"キャンペーン", "広告セット", "広告"},
        "budget_levels": {"キャンペーン", "広告セット"},
        "duplicate": True,
        "active": "ACTIVE",
        "paused": "PAUSED",
    },
    "Google": {
        "levels": {"キャンペーン", "広告グループ", "広告"},
        # 日予算はキャンペーンにしか無い
        "budget_levels": {"キャンペーン"},
        "duplicate": False,
        "active": "ENABLED",
        "paused": "PAUSED",
    },
    "TikTok": {
        "levels": {"キャンペーン", "広告グループ", "広告"},
        # 広告グループの日予算の変更は翌日から効く予約になることがあるので、
        # 巡回で動かす対象はキャンペーンにする
        "budget_levels": {"キャンペーン"},
        "duplicate": False,
        "active": "ENABLE",
        "paused": "DISABLE",
    },
    "LINEヤフー": {
        "levels": {"キャンペーン", "広告グループ", "広告"},
        "budget_levels": {"キャンペーン"},
        "duplicate": False,
        "active": "ACTIVE",
        "paused": "PAUSED",
    },
}

# 通貨の最小単位から通貨の額へ直すときに割る数（Meta の予算など）。
# 表に無い通貨では、金額を使うルールを判定しない（「たぶん 100」で進めない）。
# 足すときは媒体の公式の通貨の表で確かめる。
CURRENCY_OFFSET: dict[str, int] = {"JPY": 1, "USD": 100}

METRICS = {"CPA", "CTR", "CPC", "CPM", "消化額", "成果の件数"}
MONEY_METRICS = {"CPA", "CPC", "CPM", "消化額"}
COMPARISONS = {"より大きい", "より小さい"}
ACTIONS = {"通知する", "停止する", "日予算を減らす", "日予算を増やす", "複製する", "配信を開始する"}
BUDGET_ACTIONS = {"日予算を減らす", "日予算を増やす"}
# 支出が増える向きの操作。ルールを人が承認していなければ実行しない
SPEND_UP_ACTIONS = {"日予算を増やす", "配信を開始する"}
KIND_METRIC = "広告の実績"
KIND_SCHEDULE = "曜日と時刻"
WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]
UNITS = {"major", "minor", "micros"}

EXECUTE, PROPOSE, SKIP = "実行する", "提案する", "見送る"


class InputError(Exception):
    """ルールや実績を読み込めなかった。何も実行させない。"""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


# --------------------------------------------------------------------------
# 読み込み
# --------------------------------------------------------------------------


def load_json(path: str, label: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise InputError([f"{label}が見つかりません: {path}"])
    except json.JSONDecodeError as exc:
        raise InputError([f"{label}を JSON として読めません: {path}（{exc}）"])


def load_rules(path: str) -> list[dict[str, Any]]:
    data = load_json(path, "ルールのファイル")
    rules = data.get("rules") if isinstance(data, dict) else data
    if not isinstance(rules, list):
        raise InputError(['ルールのファイルは {"rules": [...]} の形にしてください'])
    errors: list[str] = []
    names: set[str] = set()
    for index, rule in enumerate(rules, start=1):
        if not isinstance(rule, dict):
            errors.append(f"ルール {index}: オブジェクトではありません")
            continue
        label = f"ルール {index}「{rule.get('name') or '名前なし'}」"
        for problem in validate_rule(rule):
            errors.append(f"{label}: {problem}")
        name = str(rule.get("name") or "")
        if name and name in names:
            errors.append(f"{label}: 同じ名前のルールが 2 つあります（名前は実行の記録の照合に使います）")
        names.add(name)
    if errors:
        raise InputError(errors)
    return rules


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_rule(rule: dict[str, Any]) -> list[str]:
    """読み込んだ時点で止める理由の一覧。空なら使ってよい。

    媒体でできない操作を書いたルールを実行時にだけ失敗させると、
    巡回のたびに「失敗しました」が流れ続ける。読み込みで止める。
    """
    problems: list[str] = []
    if not str(rule.get("name") or "").strip():
        problems.append("name（ルールの名前）がありません")

    media = rule.get("media")
    limits = MEDIA.get(str(media))
    if limits is None:
        problems.append(f"media は {' / '.join(MEDIA)} のいずれかにしてください（指定: {media}）")

    action = rule.get("action")
    if action not in ACTIONS:
        problems.append(f"action は {' / '.join(sorted(ACTIONS))} のいずれかにしてください（指定: {action}）")

    target = rule.get("target") if isinstance(rule.get("target"), dict) else {}
    level = target.get("level")
    ids = target.get("ids")
    if not isinstance(ids, list):
        problems.append("target.ids は配列にしてください（空の配列は「その階層のすべて」）")
        ids = []
    if limits is not None and level not in limits["levels"]:
        problems.append(
            f"{media} の target.level は {' / '.join(sorted(limits['levels']))} のいずれかです（指定: {level}）"
        )

    condition = rule.get("condition") if isinstance(rule.get("condition"), dict) else {}
    kind = condition.get("kind")
    if kind == KIND_METRIC:
        if condition.get("metric") not in METRICS:
            problems.append(f"condition.metric は {' / '.join(sorted(METRICS))} のいずれかです")
        if condition.get("comparison") not in COMPARISONS:
            problems.append("condition.comparison は「より大きい」か「より小さい」です")
        if not is_number(condition.get("threshold")):
            problems.append("condition.threshold（数値）がありません")
        if not (isinstance(rule.get("window_days"), int) and rule["window_days"] > 0):
            problems.append("window_days（集計期間の日数）を 1 以上の整数で書いてください")
        if not (is_number(rule.get("min_spend")) and rule["min_spend"] > 0):
            # 0 のままだと、ほとんど広告費を使っていない対象まで判定してしまう
            problems.append("min_spend（最低消化額）を 0 より大きい値で書いてください")
        for key in ("min_conversions", "max_conversions"):
            if key in rule and not is_number(rule[key]):
                problems.append(f"{key} は数値にしてください")
        if action == "配信を開始する":
            problems.append("配信の開始は「曜日と時刻」の条件でだけ書けます（時刻をルールに固定するため）")
    elif kind == KIND_SCHEDULE:
        days = condition.get("days")
        if not (isinstance(days, list) and days and all(d in WEEKDAYS for d in days)):
            problems.append("condition.days は 月〜日 の配列にしてください")
        hour = condition.get("hour")
        if not (isinstance(hour, int) and 0 <= hour <= 23):
            problems.append("condition.hour は 0〜23 の整数にしてください")
        if action not in {"配信を開始する", "停止する"}:
            problems.append("「曜日と時刻」の条件で書ける操作は、配信を開始する / 停止する だけです")
        if not ids:
            problems.append("「曜日と時刻」のルールは target.ids で対象を指定してください")
    else:
        problems.append(f"condition.kind は「{KIND_METRIC}」か「{KIND_SCHEDULE}」です（指定: {kind}）")

    if action in BUDGET_ACTIONS:
        if limits is not None and level not in limits["budget_levels"]:
            problems.append(
                f"{media} では {level} の日予算を巡回で動かせません"
                f"（動かせる階層: {' / '.join(sorted(limits['budget_levels']))}）"
            )
        if not (is_number(rule.get("step_percent")) and rule["step_percent"] > 0):
            problems.append("step_percent（1 回に動かす割合）を 0 より大きい値で書いてください")
        low, high = rule.get("budget_min"), rule.get("budget_max")
        if not (is_number(low) and is_number(high)):
            # 片方だけだと反対向きの歯止めが無くなる
            problems.append("budget_min と budget_max（予算の下限と上限）は両方とも書いてください")
        elif low >= high:
            problems.append("budget_min は budget_max より小さい値にしてください")

    if action == "複製する":
        if limits is not None and not limits["duplicate"]:
            problems.append(f"{media} には巡回で使える複製の手段がありません")
        if level != "キャンペーン":
            problems.append("複製できるのはキャンペーンだけです")

    if action in SPEND_UP_ACTIONS and not ids:
        # 支出が増える操作は、承認した対象だけに行う
        problems.append("支出が増える操作（日予算を増やす / 配信を開始する）は target.ids で対象を指定してください")

    if not (isinstance(rule.get("cooldown_minutes"), int) and rule["cooldown_minutes"] >= 0):
        problems.append("cooldown_minutes（同じ操作を次に行えるまでの分数）を整数で書いてください")
    if not (isinstance(rule.get("max_per_day"), int) and rule["max_per_day"] > 0):
        problems.append("max_per_day（1 日の上限回数）を 1 以上の整数で書いてください")
    if not str(rule.get("notify") or "").strip():
        problems.append("notify（通知先）がありません")

    approved = rule.get("approved")
    if approved is not None and not (
        isinstance(approved, dict) and str(approved.get("by") or "").strip() and str(approved.get("on") or "").strip()
    ):
        problems.append('approved は {"by": "承認した人", "on": "YYYY-MM-DD"} の形にしてください')
    return problems


def load_log(path: str | None) -> list[dict[str, Any]]:
    if not path or not Path(path).exists():
        return []
    entries: list[dict[str, Any]] = []
    errors: list[str] = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            moment = datetime.fromisoformat(str(entry["time"]))
            entry["_time"] = moment if moment.tzinfo else moment.astimezone()
            entries.append(entry)
        except (json.JSONDecodeError, KeyError, ValueError):
            errors.append(f"実行の記録の {number} 行目を読めません: {path}")
    if errors:
        # 記録が読めないと、待ち時間と 1 日の上限を確かめられない
        raise InputError(errors)
    return entries


def parse_now(text: str | None) -> datetime:
    if not text:
        return datetime.now().astimezone()
    try:
        now = datetime.fromisoformat(text)
    except ValueError:
        raise InputError([f"--now は ISO 8601 の日時にしてください（指定: {text}）"])
    return now if now.tzinfo else now.astimezone()


# --------------------------------------------------------------------------
# 単位
# --------------------------------------------------------------------------


def money_divisor(unit: str, currency: str | None) -> float | None:
    """媒体が返した金額を通貨の額に直すときに割る数。分からなければ None。"""
    if unit == "major":
        return 1.0
    if unit == "micros":
        return 1_000_000.0
    if unit == "minor":
        offset = CURRENCY_OFFSET.get(str(currency or "").upper())
        return float(offset) if offset else None
    return None


def to_number(value: Any) -> float | None:
    """数値に直す。**取れていない値は None**（0 にしない）。

    64 ビットの整数を文字列で返す媒体があるので、数字の文字列も受ける。
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", ""))
        except ValueError:
            return None
    return None


def round_money(value: float, currency: str | None) -> float | int:
    if CURRENCY_OFFSET.get(str(currency or "").upper()) == 1:
        return int(round(value))
    return round(value, 2)


def metric_value(metric: str, spend: float, row: dict[str, Any]) -> tuple[float | None, str]:
    """指標の値と、計算できなかったときの理由。

    成果 0 件の CPA は None（0 円として扱わない。0 円にすると
    「より小さい」の条件に当てはまり、成果ゼロの広告が増額される）。
    率は媒体が返した値を使わず、分子と分母から計算する。CTR はパーセント。
    """
    conversions = to_number(row.get("conversions"))
    clicks = to_number(row.get("clicks"))
    impressions = to_number(row.get("impressions"))
    if metric == "消化額":
        return spend, ""
    if metric == "成果の件数":
        return (conversions, "") if conversions is not None else (None, "成果の件数が未取得")
    if metric == "CPA":
        if conversions is None:
            return None, "成果の件数が未取得"
        if conversions <= 0:
            return None, "成果 0 件のため CPA を計算できない（0 円として扱わない）"
        return spend / conversions, ""
    if metric == "CPC":
        if clicks is None:
            return None, "クリック数が未取得"
        if clicks <= 0:
            return None, "クリック 0 件のため CPC を計算できない"
        return spend / clicks, ""
    if impressions is None:
        return None, "表示回数が未取得"
    if impressions <= 0:
        return None, "表示 0 回のため計算できない"
    if metric == "CPM":
        return spend / impressions * 1000, ""
    if metric == "CTR":
        if clicks is None:
            return None, "クリック数が未取得"
        return clicks / impressions * 100, ""
    return None, f"指標を解釈できない: {metric}"


# --------------------------------------------------------------------------
# 判定
# --------------------------------------------------------------------------


def item(rule: dict[str, Any], row: dict[str, Any] | None, target_id: str, reason: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "rule": rule.get("name"),
        "media": rule.get("media"),
        "level": (rule.get("target") or {}).get("level"),
        "id": target_id,
        "name": (row or {}).get("name"),
        "action": rule.get("action"),
        "reason": reason,
        "notify": rule.get("notify"),
    }
    out.update(extra)
    return out


def recent_block(rule: dict[str, Any], target_id: str, log: list[dict[str, Any]], now: datetime) -> str:
    """待ち時間と 1 日の上限回数。止める理由があれば返す。"""
    done = [e for e in log if e.get("rule") == rule.get("name") and e.get("result") == "実行した"]
    cooldown = int(rule.get("cooldown_minutes") or 0)
    if cooldown:
        for entry in done:
            if str(entry.get("target_id")) == target_id and now - entry["_time"] < timedelta(minutes=cooldown):
                return f"待ち時間の中（前回の実行 {entry['time']} から {cooldown} 分たっていない）"
    today = [e for e in done if e["_time"].astimezone(now.tzinfo).date() == now.date()]
    if len(today) >= int(rule.get("max_per_day") or 1):
        return f"このルールの 1 日の上限回数（{rule.get('max_per_day')} 回）に達している"
    return ""


def judge(rules: list[dict[str, Any]], metrics: dict[str, Any], log: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    result: dict[str, list[dict[str, Any]]] = {EXECUTE: [], PROPOSE: [], SKIP: []}
    not_matched = 0
    planned_today: dict[str, int] = {}
    media_data = metrics.get("media") if isinstance(metrics.get("media"), dict) else {}

    for rule in rules:
        if rule.get("enabled") is False:
            continue
        media = str(rule["media"])
        limits = MEDIA[media]
        level = rule["target"]["level"]
        ids = [str(i) for i in rule["target"]["ids"]]
        data = media_data.get(media)

        # 実績が取れなかった媒体は判定しない（0 として渡さない）
        if not isinstance(data, dict) or data.get("status") != "ok":
            why = (data or {}).get("reason") if isinstance(data, dict) else None
            result[SKIP].append(item(rule, None, "", f"{media} の実績が未取得のため判定しない" + (f"（{why}）" if why else "")))
            continue

        currency = data.get("currency")
        units = data.get("units") if isinstance(data.get("units"), dict) else {}
        rows = [r for r in (data.get("rows") or []) if isinstance(r, dict) and r.get("level") == level]
        by_id: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_id.setdefault(str(row.get("id")), []).append(row)

        kind = rule["condition"]["kind"]
        if kind == KIND_SCHEDULE:
            cond = rule["condition"]
            if WEEKDAYS[now.weekday()] not in cond["days"] or now.hour != cond["hour"]:
                not_matched += 1
                continue
            for target_id in ids:
                row = (by_id.get(target_id) or [None])[0]
                decide(rule, row, target_id, f"{WEEKDAYS[now.weekday()]}曜 {now.hour} 時", limits, currency, units,
                       log, now, planned_today, result)
            continue

        targets = ids or sorted(by_id)
        for target_id in targets:
            candidates = [r for r in by_id.get(target_id, []) if r.get("window_days") == rule["window_days"]]
            if not candidates:
                result[SKIP].append(item(rule, None, target_id,
                                         f"直近 {rule['window_days']} 日で集計した実績がこの対象に無い"))
                continue
            row = candidates[0]

            metric = rule["condition"]["metric"]
            spend_raw = to_number(row.get("spend"))
            divisor = money_divisor(str(units.get("spend", "major")), currency)
            if spend_raw is None:
                result[SKIP].append(item(rule, row, target_id, "消化額が未取得"))
                continue
            if divisor is None:
                result[SKIP].append(item(rule, row, target_id,
                                         f"通貨 {currency} の金額の単位を確かめられないため判定しない"))
                continue
            spend = spend_raw / divisor

            if spend < rule["min_spend"]:
                result[SKIP].append(item(rule, row, target_id,
                                         f"最低消化額に届かない（消化額 {round_money(spend, currency)} < {rule['min_spend']}）"))
                continue

            conversions = to_number(row.get("conversions"))
            if "min_conversions" in rule or "max_conversions" in rule:
                if conversions is None:
                    result[SKIP].append(item(rule, row, target_id, "成果の件数が未取得"))
                    continue
                if "min_conversions" in rule and conversions < rule["min_conversions"]:
                    result[SKIP].append(item(rule, row, target_id,
                                             f"成果の件数が足りない（{conversions:g} 件 < {rule['min_conversions']} 件）"))
                    continue
                if "max_conversions" in rule and conversions > rule["max_conversions"]:
                    not_matched += 1
                    continue

            value, why = metric_value(metric, spend, row)
            if value is None:
                result[SKIP].append(item(rule, row, target_id, why))
                continue

            threshold = float(rule["condition"]["threshold"])
            comparison = rule["condition"]["comparison"]
            matched = value > threshold if comparison == "より大きい" else value < threshold
            if not matched:
                not_matched += 1
                continue

            shown = round_money(value, currency) if metric in MONEY_METRICS else round(value, 2)
            basis = (f"直近 {rule['window_days']} 日の {metric} {shown} が {threshold:g} {comparison}"
                     f"（消化額 {round_money(spend, currency)}"
                     + (f"、成果 {conversions:g} 件" if conversions is not None else "") + "）")
            decide(rule, row, target_id, basis, limits, currency, units, log, now, planned_today, result)

    return {
        "status": "ok",
        "now": now.isoformat(),
        EXECUTE: result[EXECUTE],
        PROPOSE: result[PROPOSE],
        SKIP: result[SKIP],
        "summary": {
            EXECUTE: len(result[EXECUTE]),
            PROPOSE: len(result[PROPOSE]),
            SKIP: len(result[SKIP]),
            "条件に当てはまらなかった件数": not_matched,
        },
    }


def decide(rule: dict[str, Any], row: dict[str, Any] | None, target_id: str, basis: str,
           limits: dict[str, Any], currency: str | None, units: dict[str, Any],
           log: list[dict[str, Any]], now: datetime, planned_today: dict[str, int],
           result: dict[str, list[dict[str, Any]]]) -> None:
    """条件に当てはまった対象 1 件を、実行する / 提案する / 見送る に振り分ける。"""
    action = rule["action"]
    name = str(rule["name"])

    block = recent_block(rule, target_id, log, now)
    if not block and planned_today.get(name, 0) + sum(
        1 for e in log
        if e.get("rule") == name and e.get("result") == "実行した"
        and e["_time"].astimezone(now.tzinfo).date() == now.date()
    ) >= int(rule["max_per_day"]):
        block = f"このルールの 1 日の上限回数（{rule['max_per_day']} 回）に達している"
    if block:
        result[SKIP].append(item(rule, row, target_id, f"{basis}。ただし{block}"))
        return

    delivery = (row or {}).get("delivery")
    args: dict[str, Any] = {}

    if action == "通知する":
        pass
    elif action == "停止する":
        if delivery == "停止中":
            result[SKIP].append(item(rule, row, target_id, f"{basis}。ただしすでに停止中"))
            return
        args = {"status": limits["paused"]}
    elif action == "複製する":
        args = {"status": limits["paused"], "note": "複製は停止状態で作る"}
    elif action == "配信を開始する":
        if delivery == "配信中":
            result[SKIP].append(item(rule, row, target_id, f"{basis}。ただしすでに配信中"))
            return
        args = {"status": limits["active"]}
    else:  # 日予算の増減
        budget_unit = str(units.get("daily_budget", "major"))
        divisor = money_divisor(budget_unit, currency)
        raw = to_number((row or {}).get("daily_budget"))
        if raw is None:
            result[SKIP].append(item(rule, row, target_id, f"{basis}。ただし現在の日予算が未取得"))
            return
        if divisor is None:
            result[SKIP].append(item(rule, row, target_id,
                                     f"{basis}。ただし通貨 {currency} の予算の単位を確かめられないため動かさない"))
            return
        current = raw / divisor
        step = float(rule["step_percent"])
        low, high = float(rule["budget_min"]), float(rule["budget_max"])
        if action == "日予算を増やす":
            if (row or {}).get("learning") is True:
                result[SKIP].append(item(rule, row, target_id, f"{basis}。ただし学習期間中のため増額しない"))
                return
            if current >= high:
                result[SKIP].append(item(rule, row, target_id,
                                         f"{basis}。ただし日予算がルールの上限（{high:g}）に達している"))
                return
            new = current * (1 + step / 100)
            over = new > high
        else:
            if current <= low:
                result[SKIP].append(item(rule, row, target_id,
                                         f"{basis}。ただし日予算がルールの下限（{low:g}）に達している"))
                return
            new = max(current * (1 - step / 100), low)
            over = False
        new_rounded = round_money(new, currency)
        args = {
            "currency": currency,
            "from": round_money(current, currency),
            "to": new_rounded,
            "to_in_media_unit": int(round(float(new_rounded) * divisor)),
            "media_unit": budget_unit,
        }
        if over:
            # 上限を超える増額は実行しない。提案として通知する
            result[PROPOSE].append(item(rule, row, target_id,
                                        f"{basis}。{step:g}% 増やすとルールの上限（{high:g}）を超えるため実行しない",
                                        args=args))
            return

    if action in SPEND_UP_ACTIONS and not rule.get("approved"):
        result[PROPOSE].append(item(rule, row, target_id,
                                    f"{basis}。支出が増える操作だが、ルールが未承認（approved が無い）のため実行しない",
                                    args=args))
        return

    planned_today[name] = planned_today.get(name, 0) + 1
    result[EXECUTE].append(item(rule, row, target_id, basis, args=args))


# --------------------------------------------------------------------------
# コマンド
# --------------------------------------------------------------------------


def cmd_check(args: argparse.Namespace) -> dict[str, Any]:
    rules = load_rules(args.rules)
    enabled = [r for r in rules if r.get("enabled") is not False]
    return {
        "status": "ok",
        "rules": len(rules),
        "enabled": len(enabled),
        "未承認の支出が増えるルール": [
            r["name"] for r in enabled if r["action"] in SPEND_UP_ACTIONS and not r.get("approved")
        ],
    }


def cmd_judge(args: argparse.Namespace) -> dict[str, Any]:
    rules = load_rules(args.rules)
    metrics = load_json(args.metrics, "実績のファイル")
    if not isinstance(metrics, dict) or not isinstance(metrics.get("media"), dict):
        raise InputError(['実績のファイルは {"media": {"Meta": {...}}} の形にしてください'])
    for media, data in metrics["media"].items():
        if isinstance(data, dict) and data.get("status") == "ok":
            for key, unit in (data.get("units") or {}).items():
                if unit not in UNITS:
                    raise InputError([f"{media} の units.{key} は major / minor / micros のいずれかです（指定: {unit}）"])
    return judge(rules, metrics, load_log(args.log), parse_now(args.now))


def cmd_record(args: argparse.Namespace) -> dict[str, Any]:
    entry = {
        "time": parse_now(args.now).isoformat(),
        "rule": args.rule,
        "target_id": args.target_id,
        "action": args.action,
        "result": args.result,
        "detail": args.detail or "",
    }
    path = Path(args.log)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return {"status": "ok", "recorded": entry}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="巡回の判定。ルールと実績から、操作を「実行する / 提案する / 見送る」に分けて JSON で返す。")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="ルールのファイルを検査する（何も判定しない）")
    p_check.add_argument("--rules", required=True, help="rules.json のパス")
    p_check.set_defaults(func=cmd_check)

    p_judge = sub.add_parser("judge", help="ルールと実績から判定する")
    p_judge.add_argument("--rules", required=True, help="rules.json のパス")
    p_judge.add_argument("--metrics", required=True, help="実績のファイル（JSON）のパス")
    p_judge.add_argument("--log", help="実行の記録（JSONL）のパス。待ち時間と 1 日の上限の確認に使う")
    p_judge.add_argument("--now", help="判定の基準にする日時（ISO 8601）。省略すると現在の時刻")
    p_judge.set_defaults(func=cmd_judge)

    p_record = sub.add_parser("record", help="実行の記録に 1 行追記する")
    p_record.add_argument("--log", required=True, help="実行の記録（JSONL）のパス")
    p_record.add_argument("--rule", required=True, help="ルールの名前")
    p_record.add_argument("--target-id", default="", help="対象の ID")
    p_record.add_argument("--action", required=True, help="操作")
    p_record.add_argument("--result", required=True, choices=["実行した", "失敗した", "提案した", "見送った"])
    p_record.add_argument("--detail", help="理由や結果の補足")
    p_record.add_argument("--now", help="記録する日時（ISO 8601）。省略すると現在の時刻")
    p_record.set_defaults(func=cmd_record)

    args = parser.parse_args(argv)
    try:
        output = args.func(args)
        code = 0
    except InputError as exc:
        output = {"status": "error", "errors": exc.errors, "note": "何も実行しないでください"}
        code = 1
    json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
