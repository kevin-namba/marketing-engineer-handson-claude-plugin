#!/usr/bin/env python3
"""動画ファイルを、AI が読み取れる形（静止画・一覧画像・音声）に分ける。

要るもの: ffmpeg と ffprobe。Python は標準ライブラリだけ。
動画はローカルのファイルだけを受け取る（URL からの取得はしない）。

使い方::

    python3 extract_frames.py --video ref.mp4 --out teardown/ref01 \\
        --source-url "https://example.com/..." --fetched-at 2026-10-04

出力::

    <out>/meta.json          尺・解像度・フレームレート・参照元の URL・取得日
    <out>/frames/f_0000_t0.00.jpg …   --fps の間隔の静止画（既定 4 = 0.25 秒ごと）
    <out>/sheets/sheet_000.jpg …      静止画を時刻順に並べた一覧画像（既定 4×5 枚 = 5 秒ぶん）
    <out>/audio.m4a          音声（文字起こし用。音声が無い動画では作らない）
    <out>/silence.txt        無音の区間（発話の区間を見つける手がかり。文字起こしの代わりにはならない）
    <out>/scenes.txt         画面が大きく切り替わった時刻（カットの候補）

結果は JSON で標準出力に出る。失敗したときは ``{"error": ..., "hint": ...}`` と終了コード 1。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

MAX_DURATION_SEC = 180


def emit(payload: dict[str, Any], code: int = 0) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    raise SystemExit(code)


def die(message: str, **extra: Any) -> None:
    emit({"error": message, **extra}, code=1)


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True)


def probe(video: Path) -> dict[str, Any]:
    proc = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(video)])
    if proc.returncode != 0:
        die(f"ffprobe で読めませんでした: {proc.stderr.strip()[-300:]}", hint="動画ファイルが壊れていないかを確かめる")
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not v:
        die("映像のストリームがありません")
    num, _, den = (v.get("r_frame_rate") or "0/1").partition("/")
    try:
        frame_rate = round(float(num) / float(den or 1), 3)
    except (ValueError, ZeroDivisionError):
        frame_rate = None
    return {
        "duration_sec": round(float(data.get("format", {}).get("duration") or 0), 3),
        "width": v.get("width"),
        "height": v.get("height"),
        "frame_rate": frame_rate,
        "has_audio": a is not None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="動画ファイルを静止画・一覧画像・音声に分ける（ffmpeg が必要）")
    parser.add_argument("--video", required=True, help="動画ファイル（ローカル）")
    parser.add_argument("--out", required=True, help="出力先のディレクトリ")
    parser.add_argument("--fps", type=float, default=4.0, help="1 秒あたりの静止画の枚数（既定 4 = 0.25 秒ごと）")
    parser.add_argument("--width", type=int, default=540, help="静止画の幅（既定 540px。読み取れる範囲で小さくする）")
    parser.add_argument("--tile", default="4x5", help="一覧画像 1 枚に並べる列×行（既定 4x5）")
    parser.add_argument("--scene-threshold", type=float, default=0.3, help="カットの候補とみなす変化の大きさ（0〜1）")
    parser.add_argument("--source-url", default="", help="参照元の URL（meta.json に残す）")
    parser.add_argument("--fetched-at", default="", help="取得日（meta.json に残す）")
    parser.add_argument("--allow-long", action="store_true", help=f"{MAX_DURATION_SEC} 秒を超える動画も処理する")
    args = parser.parse_args()

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            die(f"{tool} が見つかりません",
                hint="ffmpeg を入れる（macOS: brew install ffmpeg）。入れられないときは、利用者に数秒おきのスクリーンショットと文字起こしを渡してもらう")

    video = Path(args.video).expanduser().resolve()
    if not video.is_file():
        die(f"動画ファイルがありません: {video}", hint="URL ではなく、保存済みの動画ファイルを渡す")
    if not re.fullmatch(r"\d+x\d+", args.tile):
        die("--tile は 4x5 のように 列x行 で渡す")
    cols, rows = (int(n) for n in args.tile.split("x"))

    meta = probe(video)
    if meta["duration_sec"] > MAX_DURATION_SEC and not args.allow_long:
        die(f"尺が {meta['duration_sec']} 秒あります（上限 {MAX_DURATION_SEC} 秒）",
            hint="短尺動画の分解用。長い動画は分解したい区間を切り出してから渡すか、--allow-long を付ける")

    out = Path(args.out).expanduser().resolve()
    frames_dir, sheets_dir = out / "frames", out / "sheets"
    frames_dir.mkdir(parents=True, exist_ok=True)
    sheets_dir.mkdir(parents=True, exist_ok=True)
    for stale in [*frames_dir.glob("*.jpg"), *sheets_dir.glob("*.jpg")]:  # 前回の出力を混ぜない
        stale.unlink()

    # 1. 静止画（--fps の間隔）
    proc = run(["ffmpeg", "-y", "-v", "error", "-i", str(video),
                "-vf", f"fps={args.fps},scale={args.width}:-2", "-q:v", "4",
                str(frames_dir / "raw_%04d.jpg")])
    if proc.returncode != 0:
        die(f"静止画を取り出せませんでした: {proc.stderr.strip()[-300:]}")
    frames = []
    for index, path in enumerate(sorted(frames_dir.glob("raw_*.jpg"))):
        t = index / args.fps
        target = frames_dir / f"f_{index:04d}_t{t:.2f}.jpg"
        path.rename(target)
        frames.append({"index": index, "time_sec": round(t, 2), "file": str(target.relative_to(out))})
    if not frames:
        die("静止画が 1 枚も取り出せませんでした")

    # 2. 一覧画像（時刻順に左上から右下へ）
    per_sheet = cols * rows
    proc = run(["ffmpeg", "-y", "-v", "error", "-i", str(video),
                "-vf", f"fps={args.fps},scale=270:-2,tile={cols}x{rows}:padding=4:margin=4", "-q:v", "4",
                str(sheets_dir / "sheet_%03d.jpg")])
    sheets = []
    if proc.returncode == 0:
        for index, path in enumerate(sorted(sheets_dir.glob("sheet_*.jpg"))):
            start = index * per_sheet / args.fps
            end = min((index + 1) * per_sheet / args.fps, meta["duration_sec"])
            sheets.append({"file": str(path.relative_to(out)), "from_sec": round(start, 2), "to_sec": round(end, 2)})

    # 3. 音声と無音の区間
    audio_file, silence_file = "", ""
    if meta["has_audio"]:
        audio = out / "audio.m4a"
        proc = run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
                    "-c:a", "aac", "-b:a", "64k", str(audio)])
        if proc.returncode == 0 and audio.exists() and audio.stat().st_size > 0:
            audio_file = audio.name
        else:
            audio.unlink(missing_ok=True)
        proc = run(["ffmpeg", "-v", "info", "-i", str(video), "-af", "silencedetect=noise=-30dB:d=0.5",
                    "-f", "null", "-"])
        lines = [ln.split("] ", 1)[-1] for ln in proc.stderr.splitlines() if "silence_" in ln]
        (out / "silence.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        silence_file = "silence.txt"

    # 4. カットの候補
    proc = run(["ffmpeg", "-v", "info", "-i", str(video),
                "-vf", f"select='gt(scene,{args.scene_threshold})',showinfo", "-f", "null", "-"])
    cuts = [round(float(m), 2) for m in re.findall(r"pts_time:([0-9.]+)", proc.stderr)]
    (out / "scenes.txt").write_text("\n".join(f"{c:.2f}" for c in cuts) + "\n", encoding="utf-8")

    meta_out = {
        "video": video.name,
        "source_url": args.source_url or "未取得",
        "fetched_at": args.fetched_at or "未取得",
        **meta,
        "fps_extracted": args.fps,
        "frame_count": len(frames),
        "cut_candidates_sec": cuts,
        "cut_count_estimate": len(cuts) + 1,
        "avg_cut_length_sec": round(meta["duration_sec"] / (len(cuts) + 1), 2) if meta["duration_sec"] else None,
    }
    (out / "meta.json").write_text(json.dumps(meta_out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    emit({
        "ok": True,
        "out": str(out),
        "meta": meta_out,
        "sheets": sheets,
        "frames_dir": "frames",
        "audio": audio_file or "なし（音声のストリームが無い、または取り出せなかった）",
        "silence": silence_file or "なし",
        "note": "文字起こしは含まれない。audio.m4a を音声認識にかけるか、利用者の文字起こしを使う。無ければ発話の欄は「未取得」と書く",
    })


if __name__ == "__main__":
    main()
