#!/usr/bin/env python3
"""営業用の送信ドメインの DNS 設定（SPF・DMARC・DKIM・MX）の有無を確かめる。

標準ライブラリだけで動く。DNS の問い合わせには OS の dig か nslookup を使う。
確かめるのはレコードの有無と書式まで。受信側で実際にどう判定されるかは、テスト送信のヘッダで人が確かめる。
引けなかった項目は「未取得」と出す（「設定なし」と区別する）。

  python3 check_sending_domain.py --domain example-info.com
  python3 check_sending_domain.py --domain example-info.com --dkim-selector selector1 --json

DKIM のセレクタ名は送信サービスごとに違う。送信サービスの管理画面で確かめて渡す。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys


def query(record_type: str, name: str, timeout: int) -> list[str] | None:
    """レコードの値の一覧を返す。レコードが無ければ空の一覧、引けなければ None。"""
    try:
        if shutil.which("dig"):
            done = subprocess.run(
                ["dig", "+short", f"+time={timeout}", "+tries=1", record_type, name],
                capture_output=True, text=True, timeout=timeout + 3)
            if done.returncode != 0:
                return None
            lines = [line.strip() for line in done.stdout.splitlines() if line.strip() and not line.startswith(";")]
            if record_type == "TXT":
                return ["".join(re.findall(r'"([^"]*)"', line)) or line for line in lines]
            return lines
        if shutil.which("nslookup"):
            done = subprocess.run(
                ["nslookup", f"-type={record_type.lower()}", name],
                capture_output=True, text=True, timeout=timeout + 3)
            text = done.stdout + done.stderr
            if record_type == "TXT":
                values = []
                for line in text.splitlines():
                    if "text =" in line or "\t\"" in line or line.strip().startswith('"'):
                        joined = "".join(re.findall(r'"([^"]*)"', line))
                        if joined:
                            values.append(joined)
                return values
            if record_type == "MX":
                return [line.split("mail exchanger =")[-1].strip()
                        for line in text.splitlines() if "mail exchanger" in line.lower()]
            return []
    except (subprocess.TimeoutExpired, OSError):
        return None
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="送信ドメインの SPF・DMARC・DKIM・MX の設定の有無を確かめる。")
    parser.add_argument("--domain", required=True, help="営業用の送信ドメイン（例: example-info.com）")
    parser.add_argument("--dkim-selector", action="append", default=[],
                        help="DKIM のセレクタ名（複数指定可）。省略すると DKIM は「未取得」")
    parser.add_argument("--timeout", type=int, default=5, help="DNS の待ち時間（秒。既定 5）")
    parser.add_argument("--json", action="store_true", help="結果を JSON で出す")
    args = parser.parse_args()

    domain = args.domain.strip().lower().rstrip(".")
    if not (shutil.which("dig") or shutil.which("nslookup")):
        message = "dig も nslookup も見つかりません。DNS を引ける環境で実行するか、DNS の管理画面で確かめてください。"
        if args.json:
            print(json.dumps({"error": message}, ensure_ascii=False))
        else:
            print(message)
        return 0

    checks: list[dict[str, str]] = []

    def add(item: str, status: str, value: str, advice: str) -> None:
        checks.append({"item": item, "status": status, "value": value, "advice": advice})

    txt = query("TXT", domain, args.timeout)
    if txt is None:
        add("SPF", "未取得", "", "DNS を引けなかった。時間を置いて再実行する")
    else:
        spf = [value for value in txt if value.lower().startswith("v=spf1")]
        if not spf:
            add("SPF", "設定なし", "", "送信サービスが指定する SPF レコードを TXT に追加する")
        elif len(spf) > 1:
            add("SPF", "要修正", " | ".join(spf), "SPF レコードが複数ある。1 つにまとめる")
        elif re.search(r"\+all\b", spf[0]):
            add("SPF", "要修正", spf[0], "+all は誰でも名乗れる設定。~all か -all にする")
        elif not re.search(r"[~\-?]all\b", spf[0]) and "redirect=" not in spf[0]:
            add("SPF", "要確認", spf[0], "all の指定が無い。末尾を確かめる")
        else:
            add("SPF", "設定あり", spf[0], "")

    dmarc = query("TXT", f"_dmarc.{domain}", args.timeout)
    if dmarc is None:
        add("DMARC", "未取得", "", "DNS を引けなかった。時間を置いて再実行する")
    else:
        records = [value for value in dmarc if value.lower().startswith("v=dmarc1")]
        if not records:
            add("DMARC", "設定なし", "", "_dmarc のサブドメインに DMARC レコードを追加する")
        else:
            policy = re.search(r"\bp=(\w+)", records[0])
            value = policy.group(1).lower() if policy else ""
            if not value:
                add("DMARC", "要修正", records[0], "p= の指定が無い")
            elif value == "none":
                add("DMARC", "設定あり", records[0], "p=none は監視だけ。レポートを確かめてから quarantine / reject を検討する")
            else:
                add("DMARC", "設定あり", records[0], "")

    if not args.dkim_selector:
        add("DKIM", "未取得", "", "セレクタ名が要る。送信サービスの管理画面で確かめて --dkim-selector で渡す")
    for selector in args.dkim_selector:
        name = f"{selector}._domainkey.{domain}"
        values = query("TXT", name, args.timeout)
        cname = query("CNAME", name, args.timeout) if not values else []
        if values is None:
            add(f"DKIM（{selector}）", "未取得", "", "DNS を引けなかった")
        elif any("p=" in value for value in values):
            add(f"DKIM（{selector}）", "設定あり", values[0][:80] + ("…" if len(values[0]) > 80 else ""), "")
        elif cname:
            add(f"DKIM（{selector}）", "設定あり", f"CNAME → {cname[0]}", "CNAME の先に DKIM のレコードがあるかは送信サービス側で確かめる")
        else:
            add(f"DKIM（{selector}）", "設定なし", "", "セレクタ名が正しいか確かめ、送信サービスが指定するレコードを追加する")

    mx = query("MX", domain, args.timeout)
    if mx is None:
        add("MX", "未取得", "", "DNS を引けなかった")
    elif not mx:
        add("MX", "設定なし", "", "このドメイン宛ての返信やバウンスの通知を受け取れない。受信の設定を確かめる")
    else:
        add("MX", "設定あり", ", ".join(mx[:3]), "")

    result = {
        "domain": domain,
        "checks": checks,
        "note": "DNS のレコードの有無と書式までの確認。受信側の判定はテスト送信のヘッダで人が確かめる。",
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"送信ドメイン: {domain}")
        for item in checks:
            line = f"- {item['item']}: {item['status']}"
            if item["value"]:
                line += f"（{item['value']}）"
            if item["advice"]:
                line += f" → {item['advice']}"
            print(line)
        print(result["note"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
