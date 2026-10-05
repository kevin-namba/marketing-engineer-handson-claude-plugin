#!/usr/bin/env python3
"""メールアドレスを、文面を書く前に費用のかからない順で検査する。

  1. 形式の検査（アドレスの文法）
  2. MX レコードの有無（DNS に問い合わせるだけ。相手には何も送信されない）
  3. ラベル（個人向けの無料メール / 役割アドレス）

標準ライブラリだけで動く。MX の問い合わせには OS の dig か nslookup を使う。
どちらも無い・引けないときは「不明」と出す（「有効」にも「無効」にも倒さない）。

  python3 check_addresses.py --in leads.csv --column email --out leads_checked.csv
  python3 check_addresses.py --address taro@example.com --address info@example.co.jp
  python3 check_addresses.py --in leads.csv --no-dns        # 形式とラベルだけ

出力の address_status は 有効 / 無効 / 不明 / 役割アドレス。SMTP での到達確認は行わない
（「有効」は「形式が正しく、ドメインがメールを受け取る設定を持つ」までを意味する）。
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import shutil
import subprocess
import sys

ADDRESS_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,}$"
)

FREE_MAIL = {
    "gmail.com", "googlemail.com", "yahoo.co.jp", "yahoo.com", "ymail.ne.jp",
    "outlook.com", "outlook.jp", "hotmail.com", "hotmail.co.jp", "live.jp", "live.com",
    "icloud.com", "me.com", "mac.com", "aol.com", "proton.me", "protonmail.com",
    "docomo.ne.jp", "ezweb.ne.jp", "au.com", "softbank.ne.jp", "i.softbank.jp",
    "nifty.com", "biglobe.ne.jp", "ocn.ne.jp", "so-net.ne.jp", "excite.co.jp",
}

ROLE_LOCAL = {
    "info", "contact", "sales", "support", "admin", "office", "inquiry", "inquiries",
    "toiawase", "otoiawase", "webmaster", "postmaster", "hello", "mail", "pr", "press",
    "recruit", "saiyo", "jinji", "soumu", "eigyo", "kouhou", "koho", "customer",
    "service", "help", "noreply", "no-reply", "reserve", "yoyaku", "shop", "order",
}


def format_ok(address: str) -> bool:
    if len(address) > 254 or ".." in address:
        return False
    local = address.split("@")[0] if "@" in address else ""
    if not local or len(local) > 64 or local.startswith(".") or local.endswith("."):
        return False
    return bool(ADDRESS_RE.match(address))


def lookup_mx(domain: str, timeout: int, cache: dict[str, str]) -> str:
    """'あり' / 'なし' / '不明' を返す。"""
    if domain in cache:
        return cache[domain]
    result = "不明"
    try:
        if shutil.which("dig"):
            done = subprocess.run(
                ["dig", "+short", f"+time={timeout}", "+tries=1", "MX", domain],
                capture_output=True, text=True, timeout=timeout + 3)
            if done.returncode == 0:
                lines = [line for line in done.stdout.splitlines() if line.strip() and not line.startswith(";")]
                # "0 ." は「メールを受け取らない」という宣言（null MX）なので「なし」として扱う
                hosts = [line.split()[1] for line in lines if re.match(r"^\d+\s+\S+", line)]
                result = "あり" if any(host != "." for host in hosts) else "なし"
        elif shutil.which("nslookup"):
            done = subprocess.run(
                ["nslookup", "-type=mx", domain],
                capture_output=True, text=True, timeout=timeout + 3)
            text = (done.stdout + done.stderr).lower()
            if "mail exchanger" in text:
                result = "あり"
            elif "nxdomain" in text or "can't find" in text or "no answer" in text or "non-existent" in text:
                result = "なし"
    except (subprocess.TimeoutExpired, OSError):
        result = "不明"
    cache[domain] = result
    return result


def check(address: str, use_dns: bool, timeout: int, cache: dict[str, str]) -> dict[str, str]:
    raw = (address or "").strip()
    out = {"address_format": "", "address_mx": "", "address_label": "", "address_status": "", "address_note": ""}
    if not raw:
        out.update(address_status="不明", address_note="アドレス未取得")
        return out
    normalized = raw.lower()
    if not format_ok(normalized):
        out.update(address_format="誤り", address_status="無効", address_note="形式の誤り")
        return out
    out["address_format"] = "正しい"
    local, domain = normalized.rsplit("@", 1)
    labels = []
    if domain in FREE_MAIL:
        labels.append("個人向けの無料メール")
    if local in ROLE_LOCAL:
        labels.append("役割アドレス")
    out["address_label"] = " / ".join(labels)

    if not use_dns:
        out.update(address_mx="未検査", address_status="不明", address_note="MX は未検査（--no-dns）")
        return out
    mx = lookup_mx(domain, timeout, cache)
    out["address_mx"] = mx
    if mx == "なし":
        out.update(address_status="無効", address_note="MX レコードなし。調査も文面の生成もしない")
    elif mx == "不明":
        out.update(address_status="不明", address_note="MX を引けなかった。不明のまま送らない")
    elif "役割アドレス" in labels:
        out.update(address_status="役割アドレス", address_note="担当者個人ではなく窓口")
    else:
        out["address_status"] = "有効"
        if labels:
            out["address_note"] = "担当者の所属を特定できない"
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="メールアドレスの形式・MX レコード・ラベルを検査する（相手には何も送信しない）。")
    parser.add_argument("--in", dest="infile", help="リード一覧（CSV）")
    parser.add_argument("--column", default="email", help="アドレスの列名（既定: email）")
    parser.add_argument("--address", action="append", default=[], help="単体で検査するアドレス（複数指定可）")
    parser.add_argument("--out", help="結果の CSV。省略すると標準出力")
    parser.add_argument("--no-dns", action="store_true", help="MX の問い合わせをしない（形式とラベルだけ）")
    parser.add_argument("--timeout", type=int, default=5, help="DNS の待ち時間（秒。既定 5）")
    args = parser.parse_args()

    if not args.infile and not args.address:
        parser.error("--in か --address のどちらかを指定してください")

    use_dns = not args.no_dns
    if use_dns and not (shutil.which("dig") or shutil.which("nslookup")):
        print("dig も nslookup も見つかりません。MX は「不明」として出します。", file=sys.stderr)
    cache: dict[str, str] = {}
    today = dt.date.today().isoformat()

    if args.address:
        results = []
        for address in args.address:
            row = {"email": address, **check(address, use_dns, args.timeout, cache), "address_checked_on": today}
            results.append(row)
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    with open(args.infile, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    if args.column not in fields:
        print(f"列がありません: {args.column}（ある列: {', '.join(fields)}）", file=sys.stderr)
        return 2

    extra = ["address_status", "address_format", "address_mx", "address_label", "address_note", "address_checked_on"]
    counts: dict[str, int] = {}
    for row in rows:
        result = check(row.get(args.column, ""), use_dns, args.timeout, cache)
        row.update(result)
        row["address_checked_on"] = today
        counts[result["address_status"]] = counts.get(result["address_status"], 0) + 1

    out_fields = fields + [name for name in extra if name not in fields]
    target = open(args.out, "w", newline="", encoding="utf-8") if args.out else sys.stdout
    try:
        writer = csv.DictWriter(target, fieldnames=out_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    finally:
        if args.out:
            target.close()
    print(" / ".join(f"{key} {value} 件" for key, value in sorted(counts.items())) + f"（検査日 {today}）",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
