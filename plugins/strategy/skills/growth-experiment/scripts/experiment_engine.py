#!/usr/bin/env python3
"""
テストの記録と判定（growth-experiment 用）。

テストを登録し、案（バリアント）ごとの実際の数字を記録し、統計（ブートストラップの
信頼区間 + Mann-Whitney U 検定）で「勝ち / 負け / まだ分からない」を判定する。
勝った案は「勝ちパターン一覧」（playbook.json）に入る。負けた案も experiments.json に残る。

依存: numpy, scipy（pip install numpy scipy）

使い方:
  # テストを登録する（判定の基準 = 指標と最小件数はここで決まり、あとから変えない）
  python3 experiment_engine.py create --agent booking-page --hypothesis "見出しを B にすると予約開始率が上がる" \
    --variable "headline" --variants '["A", "B"]' --metric "start_rate" --min-samples 14

  # 案ごとの実際の数字を 1 件ずつ記録する（例: 1 日ごとの予約開始率）
  python3 experiment_engine.py log --agent booking-page --experiment-id EXP-BOOKING-PAGE-001 --variant "B" \
    --metrics '{"start_rate": 5.1}'

  # 判定する（件数が足りなければ「まだ分からない」のまま返る）
  python3 experiment_engine.py score --agent booking-page --experiment-id EXP-BOOKING-PAGE-001

  # 一覧 / 勝ちパターン一覧 / 次に試す候補
  python3 experiment_engine.py list --agent booking-page
  python3 experiment_engine.py playbook --agent booking-page
  python3 experiment_engine.py suggest --agent booking-page

--agent はテストの単位（アカウント名・サイト名・チャネル名）。記録は既定でカレントディレクトリの
growth-tests/<agent>/ に JSON で残る（GROWTH_ENGINE_DATA_DIR で変えられる）。
作業のたびに消えない場所を指定すること。
"""
import argparse, json, os, sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import stats

# ── 設定 ──────────────────────────────────────────────────────────────


# 記録の置き場。既定はカレントディレクトリ（CLAUDE_PROJECT_DIR があればその下）の growth-tests/。
# GROWTH_ENGINE_DATA_DIR 環境変数で上書きできる。作業のたびに消えない場所を指定する。
BASE_DIR = Path(os.environ.get("GROWTH_ENGINE_DATA_DIR")
                or Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd()) / "growth-tests")

# エージェント/チャネルの分類を定義する。データが速く集まる高ボリュームチャネルは
# バリアントあたりの必要サンプルが少ない。自分の構成に合わせて調整する。
HIGH_VOLUME_AGENTS = set(os.environ.get("HIGH_VOLUME_AGENTS", "content,email").split(","))
LOW_VOLUME_AGENTS = set(os.environ.get("LOW_VOLUME_AGENTS", "seo,linkedin,blog").split(","))

# バッチモード: 単純な A/B ではなく、最大でこの数のバリアントを同時に許可する
BATCH_MODE_MAX_VARIANTS = int(os.environ.get("BATCH_MODE_MAX_VARIANTS", "10"))

# エージェント名をマーケティングチャネルにマッピングする。組織に合わせてカスタマイズ。
AGENT_CHANNEL = {
    "content":  "social",
    "email":    "email",
    "linkedin": "linkedin",
    "seo":      "seo",
    "blog":     "blog",
}

# AGENT_CHANNEL_OVERRIDES 環境変数（例: "my-brand-ig:social,my-brand-tt:social"）で
# AGENT_CHANNEL に追加/上書きマッピングを与える。未設定時は既存の AGENT_CHANNEL のみが使われ、動作は変わらない。
def _apply_agent_channel_overrides(mapping: dict, raw: str) -> None:
    """AGENT_CHANNEL_OVERRIDES の "name1:channel1,name2:channel2" 形式をパースし、
    mapping に安全にマージする（空文字・空白・コロンなしのエントリはスキップ）。"""
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        name, channel = entry.split(":", 1)
        name, channel = name.strip(), channel.strip()
        if name and channel:
            mapping[name] = channel


_apply_agent_channel_overrides(AGENT_CHANNEL, os.environ.get("AGENT_CHANNEL_OVERRIDES", ""))

# 統計パラメータ
BOOTSTRAP_ITERATIONS = int(os.environ.get("BOOTSTRAP_ITERATIONS", "1000"))
P_WINNER = float(os.environ.get("P_WINNER", "0.05"))    # 勝者判定の p 値しきい値
P_TREND = float(os.environ.get("P_TREND", "0.10"))      # 「trending」ステータスの p 値しきい値
LIFT_WIN = float(os.environ.get("LIFT_WIN", "15.0"))     # 「keep」判定に必要な最小リフト（%）


def get_min_samples(agent: str, override: int | None = None) -> int:
    """スコアリング前に必要なバリアントあたりの最小サンプル数を返す。
    高ボリュームチャネル（email、social）は少ないサンプル（10）で足りる。
    低ボリュームチャネル（SEO、blog）は信頼できるシグナルに多く（30）必要。
    明示的な override が 3 より大きければそれを優先する。
    """
    if override is not None and override > 3:
        return override
    return 10 if agent in HIGH_VOLUME_AGENTS else 30


def bootstrap_lift_ci(a_vals, b_vals, n_iter=BOOTSTRAP_ITERATIONS, ci=95):
    """リフト = (mean(b) - mean(a)) / mean(a) * 100 のブートストラップ信頼区間。
    パーセンテージで (下限, 上限) を返す。ベースラインがゼロの場合は (None, None)。
    """
    a = np.array(a_vals, dtype=float)
    b = np.array(b_vals, dtype=float)
    lifts = []
    rng = np.random.default_rng(42)
    for _ in range(n_iter):
        sa = rng.choice(a, size=len(a), replace=True)
        sb = rng.choice(b, size=len(b), replace=True)
        baseline_mean = sa.mean()
        if baseline_mean == 0:
            continue
        lifts.append((sb.mean() - baseline_mean) / baseline_mean * 100)
    if not lifts:
        return None, None
    lo = float(np.percentile(lifts, (100 - ci) / 2))
    hi = float(np.percentile(lifts, 100 - (100 - ci) / 2))
    return round(lo, 1), round(hi, 1)


def get_agent_dir(agent):
    d = BASE_DIR / agent
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_json(path, default=None):
    if path.exists():
        return json.loads(path.read_text())
    return default if default is not None else {}


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, default=str))


def next_id(agent):
    d = get_agent_dir(agent)
    experiments = load_json(d / "experiments.json", [])
    return f"EXP-{agent.upper()}-{len(experiments)+1:03d}"


def cmd_create(args):
    d = get_agent_dir(args.agent)
    experiments = load_json(d / "experiments.json", [])

    exp_id = next_id(args.agent)
    min_s = get_min_samples(args.agent, args.min_samples if args.min_samples != 3 else None)

    variants = json.loads(args.variants)
    batch_mode = getattr(args, "batch_mode", False)
    if batch_mode and len(variants) > BATCH_MODE_MAX_VARIANTS:
        print(f"バッチモードは最大 {BATCH_MODE_MAX_VARIANTS} バリアントに制限されます（指定 {len(variants)} 件）")
        variants = variants[:BATCH_MODE_MAX_VARIANTS]

    experiment = {
        "id": exp_id,
        "agent": args.agent,
        "channel": AGENT_CHANNEL.get(args.agent, "unknown"),
        "hypothesis": args.hypothesis,
        "variable": args.variable,
        "variants": variants,
        "primary_metric": args.metric,
        "cycle_hours": args.cycle_hours,
        "min_samples": min_s,
        "batch_mode": batch_mode,
        "max_variants": BATCH_MODE_MAX_VARIANTS if batch_mode else 2,
        "status": "running",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data_points": [],
        "baseline_variant": variants[0],
        "result": None,
        "winner": None
    }

    experiments.append(experiment)
    save_json(d / "experiments.json", experiments)

    # 進行中のテストの索引を更新
    active = load_json(d / "active.json", [])
    active.append({"id": exp_id, "variable": args.variable, "variants": experiment["variants"],
                    "current_variant_idx": 0})
    save_json(d / "active.json", active)

    mode_str = f"BATCH ({len(variants)} バリアント)" if batch_mode else "A/B"
    print(f"作成しました {exp_id}: {args.hypothesis}")
    print(f"   チャネル: {experiment['channel']} | 変数: {args.variable} | モード: {mode_str}")
    print(f"   バリアント: {experiment['variants']}")
    print(f"   指標: {args.metric} | サイクル: {args.cycle_hours}h | バリアントあたり最小サンプル: {min_s}")
    return exp_id


def cmd_log(args):
    d = get_agent_dir(args.agent)
    experiments = load_json(d / "experiments.json", [])

    for exp in experiments:
        if exp["id"] == args.experiment_id:
            dp = {
                "variant": args.variant,
                "metrics": json.loads(args.metrics),
                "logged_at": datetime.now(timezone.utc).isoformat(),
                "notes": args.notes or ""
            }
            exp["data_points"].append(dp)
            save_json(d / "experiments.json", experiments)
            print(f"{args.experiment_id} のバリアント '{args.variant}' にデータポイントを記録しました: {dp['metrics']}")
            return

    print(f"テスト {args.experiment_id} が見つかりません")
    sys.exit(1)


def cmd_score(args):
    d = get_agent_dir(args.agent)
    experiments = load_json(d / "experiments.json", [])

    for exp in experiments:
        if exp["id"] == args.experiment_id and exp["status"] in ("running", "active", "trending"):
            # データポイントをバリアント別にグループ化
            variant_data = {}
            for dp in exp["data_points"]:
                v = dp["variant"]
                if v not in variant_data:
                    variant_data[v] = []
                variant_data[v].append(dp["metrics"].get(exp["primary_metric"], 0))

            baseline_v = exp["baseline_variant"]
            min_samples = exp.get("min_samples",
                                  get_min_samples(exp["agent"]) if "agent" in exp else 15)

            # バリアントごとのサンプル下限を満たすか確認
            insufficient = []
            for v in list(dict.fromkeys(list(exp.get("variants", [])) + list(variant_data))):
                n_v = len(variant_data.get(v, []))
                if n_v < min_samples:
                    insufficient.append((v, n_v))

            if insufficient:
                for v, n in insufficient:
                    print(f"{exp['id']}: バリアント '{v}' は {n}/{min_samples} サンプル。データが不足しています。")
                # サンプルが少なくても trending シグナルを確認する（最低 15 件必要）
                all_counts = {v: len(data) for v, data in variant_data.items()}
                min_count = min(all_counts.values()) if all_counts else 0
                if min_count >= 15 and baseline_v in variant_data:
                    baseline_vals = variant_data[baseline_v]
                    best_trend_v, best_trend_p = None, 1.0
                    for v, vals in variant_data.items():
                        if v == baseline_v or len(vals) < 15:
                            continue
                        _, p = stats.mannwhitneyu(baseline_vals, vals, alternative="less")
                        if p < P_TREND and p < best_trend_p:
                            best_trend_p = p
                            best_trend_v = v
                    if best_trend_v:
                        exp["status"] = "trending"
                        save_json(d / "experiments.json", experiments)
                        lift = (np.mean(variant_data[best_trend_v]) - np.mean(baseline_vals)) / np.mean(baseline_vals) * 100 if np.mean(baseline_vals) else 0
                        print(f"{exp['id']}: TRENDING — '{best_trend_v}' p={best_trend_p:.3f}, lift={lift:.1f}%（確定にはさらにサンプルが必要）")
                return

            if not variant_data:
                print(f"{exp['id']}: まだデータポイントがありません。")
                return

            baseline_vals = np.array(variant_data.get(baseline_v, []), dtype=float)
            if len(baseline_vals) < min_samples:
                print(f"{exp['id']}: ベースラインバリアント '{baseline_v}' は {len(baseline_vals)}/{min_samples} サンプル。")
                return

            # ベースライン以外の全バリアントを評価
            results = []
            for v, vals in variant_data.items():
                if v == baseline_v:
                    continue
                arr = np.array(vals, dtype=float)
                baseline_mean = baseline_vals.mean()
                variant_mean  = arr.mean()
                lift = ((variant_mean - baseline_mean) / baseline_mean * 100) if baseline_mean != 0 else 0

                # Mann-Whitney U 検定（ノンパラメトリック、正規性の仮定なし）
                _, p_two = stats.mannwhitneyu(baseline_vals, arr, alternative="two-sided")
                _, p_less = stats.mannwhitneyu(baseline_vals, arr, alternative="less")

                ci_lo, ci_hi = bootstrap_lift_ci(baseline_vals.tolist(), arr.tolist())

                if p_less < P_WINNER and lift >= LIFT_WIN:
                    status = "keep"
                elif p_two < P_WINNER and lift < 0:
                    status = "crash" if lift <= -LIFT_WIN else "discard"
                elif p_less < P_TREND and len(vals) >= 15:
                    status = "trending"
                else:
                    status = "running"

                results.append({
                    "variant": v,
                    "mean": round(float(variant_mean), 2),
                    "lift_pct": round(lift, 1),
                    "p_value": round(float(p_less), 4),
                    "ci_95": [ci_lo, ci_hi],
                    "n": len(vals),
                    "status": status
                })

            baseline_mean = float(baseline_vals.mean())
            overall_result = {
                "baseline": baseline_v,
                "baseline_mean": round(baseline_mean, 2),
                "baseline_n": len(baseline_vals),
                "variants": results,
                "scored_at": datetime.now(timezone.utc).isoformat(),
                "min_samples": min_samples,
                "thresholds": {"p_winner": P_WINNER, "p_trend": P_TREND, "lift_pct_required": LIFT_WIN}
            }

            winners  = [r for r in results if r["status"] == "keep"]
            crashes  = [r for r in results if r["status"] in ("crash", "discard")]
            trending = [r for r in results if r["status"] == "trending"]

            if winners:
                best = max(winners, key=lambda r: r["lift_pct"])
                exp["status"] = "keep"
                exp["winner"] = best["variant"]
                exp["result"] = overall_result
                save_json(d / "experiments.json", experiments)

                # 勝ちパターン一覧へ追加
                playbook = load_json(d / "playbook.json", {})
                playbook[exp["variable"]] = {
                    "best": best["variant"],
                    "metric": exp["primary_metric"],
                    "avg": best["mean"],
                    "improvement": best["lift_pct"],
                    "p_value": best["p_value"],
                    "ci_95": best["ci_95"],
                    "experiment_id": exp["id"],
                    "promoted_at": datetime.now(timezone.utc).isoformat()
                }
                save_json(d / "playbook.json", playbook)

                # アクティブインデックスから削除
                active = load_json(d / "active.json", [])
                active = [a for a in active if a["id"] != exp["id"]]
                save_json(d / "active.json", active)

                print(f"{exp['id']}: KEEP — '{best['variant']}' リフト +{best['lift_pct']}% "
                      f"(p={best['p_value']}, 95% CI [{best['ci_95'][0]}, {best['ci_95'][1]}]%)")
                print(f"   勝ちパターン一覧を更新: {exp['variable']} → '{best['variant']}'")

            elif all(r["status"] in ("crash", "discard") for r in results) and results:
                worst = min(results, key=lambda r: r["lift_pct"])
                exp["status"] = "discard"
                exp["result"] = overall_result
                save_json(d / "experiments.json", experiments)
                active = load_json(d / "active.json", [])
                active = [a for a in active if a["id"] != exp["id"]]
                save_json(d / "active.json", active)
                print(f"{exp['id']}: DISCARD — ベースラインの勝ち。最良バリアント: '{worst['variant']}' "
                      f"が {worst['lift_pct']}% (p={worst['p_value']})")

            elif trending:
                exp["status"] = "trending"
                exp["result"] = overall_result
                save_json(d / "experiments.json", experiments)
                best_t = max(trending, key=lambda r: r["lift_pct"])
                print(f"{exp['id']}: TRENDING — '{best_t['variant']}' +{best_t['lift_pct']}% "
                      f"(p={best_t['p_value']}, n={best_t['n']})。データ収集を継続してください。")

            else:
                exp["status"] = "running"
                exp["result"] = overall_result
                save_json(d / "experiments.json", experiments)
                for r in results:
                    print(f"{exp['id']}: '{r['variant']}' リフト {r['lift_pct']:+.1f}%, p={r['p_value']} — running")
            return

    print(f"進行中のテスト {args.experiment_id} が見つかりません")


def cmd_list(args):
    d = get_agent_dir(args.agent)
    experiments = load_json(d / "experiments.json", [])

    status_filter = args.status or "all"
    icons = {
        "running": "[進行中]", "active": "[進行中]",
        "trending": "[傾向あり]",
        "keep": "[勝ち]", "promoted": "[勝ち]",
        "discard": "[負け]", "killed": "[負け]",
        "crash": "[大きく悪化]",
        "inconclusive": "[判定できず]"
    }
    for exp in experiments:
        s = exp["status"]
        if status_filter != "all" and s != status_filter:
            aliases = {"active": "running", "promoted": "keep", "killed": "discard"}
            if aliases.get(s) != status_filter and s != status_filter:
                continue
        dp_count = len(exp.get("data_points", []))
        icon = icons.get(s, "[?]")
        ch = exp.get("channel", AGENT_CHANNEL.get(exp["agent"], "?"))
        print(f"{icon} {exp['id']}: {exp['hypothesis']}")
        print(f"   変数: {exp['variable']} | チャネル: {ch} | ステータス: {s} | データポイント: {dp_count}")
        if exp.get("winner"):
            result = exp.get("result", {})
            lift = ""
            if isinstance(result, dict):
                for vr in result.get("variants", []):
                    if vr["variant"] == exp["winner"]:
                        lift = f" (リフト {vr['lift_pct']:+.1f}%, p={vr['p_value']})"
                        break
            print(f"   勝者: {exp['winner']}{lift}")
        print()


def cmd_playbook(args):
    d = get_agent_dir(args.agent)
    playbook = load_json(d / "playbook.json", {})

    if not playbook:
        print(f"{args.agent} の勝ちパターン一覧はまだ空です。")
        return

    print(f"{args.agent.upper()} の勝ちパターン一覧（テストで確かめた型）\n")
    for variable, entry in playbook.items():
        p_str = f", p={entry['p_value']}" if "p_value" in entry else ""
        ci_str = f", 95% CI {entry['ci_95']}" if "ci_95" in entry else ""
        print(f"  {variable}: '{entry['best']}' ({entry['metric']} で +{entry['improvement']}%{p_str}{ci_str})")
        print(f"    出典: {entry['experiment_id']} | 昇格日: {entry['promoted_at'][:10]}")
        print()


def cmd_suggest(args):
    d = get_agent_dir(args.agent)
    experiments = load_json(d / "experiments.json", [])
    playbook = load_json(d / "playbook.json", {})

    # チャネルごとにテスト可能なカテゴリを定義する。ビジネスに合わせてカスタマイズ。
    categories = {
        "content": ["hook_style", "post_format", "cta_type", "post_time", "thread_length",
                     "emoji_usage", "data_vs_narrative", "question_vs_statement"],
        "email": ["subject_line_style", "opener_type", "email_length", "personalization_depth",
                   "cta_style", "send_time", "follow_up_timing", "social_proof_type"],
        "linkedin": ["inmail_opener", "role_framing", "company_pitch", "personalization_level",
                      "subject_line", "follow_up_cadence"],
        "blog": ["headline_style", "content_format", "platform_priority", "visual_style",
                  "posting_time", "content_length"],
        "seo": ["title_tag_format", "meta_description_style", "content_structure",
                 "internal_linking", "heading_format"]
    }

    tested = set(playbook.keys())
    tested.update(e["variable"] for e in experiments if e["status"] in ("running", "active", "trending"))
    agent_cats = categories.get(args.agent, [])
    untested = [c for c in agent_cats if c not in tested]
    min_s = get_min_samples(args.agent)
    ch = AGENT_CHANNEL.get(args.agent, "?")

    if not agent_cats:
        print(f"{args.agent} には標準の候補一覧がありません。計画シートで点を付けた案から選んでください。")
    elif untested:
        print(f"{args.agent} の次のテスト候補（{ch}、バリアントあたり最小 {min_s} サンプル）:")
        for cat in untested[:3]:
            print(f"   → {cat}")
    else:
        print(f"{args.agent} は標準の候補をすべてテスト済みです。")


def main():
    parser = argparse.ArgumentParser(description="テストの記録と判定（create → log → score）")
    sub = parser.add_subparsers(dest="command")

    p_create = sub.add_parser("create", help="テストを登録する")
    p_create.add_argument("--agent", required=True, help="テストの単位（アカウント名・サイト名・チャネル名）")
    p_create.add_argument("--hypothesis", required=True, help="テスト内容と期待する結果")
    p_create.add_argument("--variable", required=True, help="テストする変数（例: hook_style）")
    p_create.add_argument("--variants", required=True, help="バリアント名の JSON 配列")
    p_create.add_argument("--metric", required=True, help="最適化する主要指標（例: impressions）")
    p_create.add_argument("--cycle-hours", type=int, default=24, help="テスト 1 サイクルあたりの時間（デフォルト: 24）")
    p_create.add_argument("--min-samples", type=int, default=3,
                          help="バリアントあたりの最小サンプルを上書き（デフォルト: チャネルのボリュームに応じて自動）")
    p_create.add_argument("--batch-mode", action="store_true",
                          help="バッチモードを有効化: 最大 10 バリアントを同時に")

    p_log = sub.add_parser("log", help="進行中のテストに実際の数字を 1 件記録する")
    p_log.add_argument("--agent", required=True)
    p_log.add_argument("--experiment-id", required=True)
    p_log.add_argument("--variant", required=True)
    p_log.add_argument("--metrics", required=True, help="指標値の JSON オブジェクト")
    p_log.add_argument("--notes", default="")

    p_score = sub.add_parser("score", help="テストを判定する（勝った案は勝ちパターン一覧に入る）")
    p_score.add_argument("--agent", required=True)
    p_score.add_argument("--experiment-id", required=True)

    p_list = sub.add_parser("list", help="テストを一覧する")
    p_list.add_argument("--agent", required=True)
    p_list.add_argument("--status", default="all", help="ステータスで絞り込み（running/trending/keep/discard/all）")

    p_play = sub.add_parser("playbook", help="勝ちパターン一覧を表示する")
    p_play.add_argument("--agent", required=True)

    p_sug = sub.add_parser("suggest", help="まだ試していない変数から次のテスト候補を出す")
    p_sug.add_argument("--agent", required=True)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    {"create": cmd_create, "log": cmd_log, "score": cmd_score,
     "list": cmd_list, "playbook": cmd_playbook, "suggest": cmd_suggest}[args.command](args)


if __name__ == "__main__":
    main()
