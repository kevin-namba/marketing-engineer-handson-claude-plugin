---
name: image-video-gen
description: >-
  画像と動画を生成する。生成の API キーが無いときは HTML で組んで画像まで作る。
  生成物の隣に「どのモデルに何を投げたか」の履歴を必ず残す。
  「画像を生成して」「バナーを画像にして」「図解を作って」「この画像を直して」「動画を生成して」で使う。
  **画像を作る経路はここ 1 つ**。ブラウザの画面を撮って自作しない（履歴が残らない）。
  ※バナーの構成と JSON の設計書は banner-design、動画全体の作り方の選択は video-production、
  画像の代替テキストや軽量化など、ページへの載せ方は扱わない（第 6 章）。
---

# 画像・動画の生成

画像を作る手順をこの Skill にまとめ、どの方法で作っても同じ形の履歴（サイドカー）が画像の隣に残るようにしている。

## 最初に確定すること

- 認証情報は環境変数（`GEMINI_API_KEY` / `OPENAI_API_KEY`）から読む。キーの値を会話やファイルに書き写さない。
  未設定のとき、先回りして人にキーを聞かない。まず別の経路で作る
- 生成 API は 1 枚ごとに実費がかかる。静止画は数枚ずつ検品しながら、動画は本数と見込み時間を伝えてから生成する
- 主役になる実物の素材（店舗・商品・人物の写真）の有無が与件に無ければ、生成を始める前に 1 回だけ確認する。
  図解・背景・装飾は確認なしで進める

## 手順

1. 用途を見て経路を選ぶ。片方の API キーが未設定・失敗なら、もう片方に切り替える

   | 用途 | まず選ぶ経路 |
   |---|---|
   | 写真風・キービジュアル・背景・商品カット | 写真に強いモデル（執筆時点では Gemini 系。`--provider gemini`） |
   | 文字が入る図解・インフォグラフィック | 文字に強いモデル（執筆時点では OpenAI の GPT Image 系。`--provider openai`） |
   | 実在の写真に帯と文字を重ねる／同じデザインで差し替えて量産する／API キーが 1 つも無い | HTML で組む（`render_html.py`） |
2. 設計仕様を渡す。文章ではなく JSON の設計書をそのままプロンプトにする
   （書き方は `${CLAUDE_PLUGIN_ROOT}/skills/banner-design/references/json-spec.md`）。
   写真や背景だけなら、被写体・光・構図・入れないものを短く書く
3. 生成し、結果の JSON を読む。スクリプトは画像の隣に `<画像ファイル名>.json`（サイドカー）を書く。
   `error` があれば画像は書かれていないので、`hint` に従って経路を切り替える
4. 画像を開いて検品する。生成 AI: 書いていない文字・誤字・要素の抜け（誤字が 1 文字でもあれば JSON を確かめて作り直す）。
   HTML: はみ出し・意図しない折り返し・写真の引き伸ばし（結果の `warnings`）・実寸での読みやすさ
5. 「バッジを足して」のような直しは作り直さず、元の画像を `--ref` で渡して編集する（OpenAI は `--mask` で範囲を指定できる）。
   変える場所と変えない場所を両方書き、別の名前で保存する。誤字の修正にはこの方法を使わない

```bash
# 写真風の背景（Gemini。比率と解像度ティアで指定）
python3 "${CLAUDE_PLUGIN_ROOT}/skills/image-video-gen/scripts/generate_image.py" \
  --provider gemini --prompt "朝もやの山あい、紅葉の木立、朝日、建物と人物なし、写真、広角" \
  --out out/yoyaku3d_bg_1x1_v01.png --aspect 1:1 --size 2K

# 文字入りのバナー・図解（OpenAI。ピクセルで指定。JSON の設計書をファイルで渡す）
python3 "${CLAUDE_PLUGIN_ROOT}/skills/image-video-gen/scripts/generate_image.py" \
  --provider openai --prompt-file out/spec_1080x1080.json \
  --out out/yoyaku3d_after_catch_meta_1080x1080_v01.png --size 1024x1024 \
  --meta appeal=yoyaku3d --meta copy_type=after --meta layout_type=catchcopy --meta placement=meta_feed

# HTML で組んだバナー（API キー不要。Playwright、無ければ Chrome のヘッドレス撮影）
python3 "${CLAUDE_PLUGIN_ROOT}/skills/image-video-gen/scripts/render_html.py" \
  --html out/banner.html --out out/yoyaku3d_after_catch_meta_1080x1080_v01.png \
  --width 1080 --height 1080 --scale 2 --meta appeal=yoyaku3d
```

- `generate_image.py` は標準ライブラリだけで動く。モデル名は `--model` か環境変数 `GEMINI_IMAGE_MODEL` / `OPENAI_IMAGE_MODEL` で上書きできる
- `id` や `appeal` などの欄は `--meta key=value` で渡す。派生の案では `--variant-of`（どのクリエイティブから作ったか）と
  `--changed`（何を変えたか）を必ず渡す
- ファイル名は `{訴求軸}_{コピー型}_{構成型}_{媒体}_{サイズ}_{版}`
- サイドカーの形、結果の読み方、2 つの API の違いは `references/api-notes.md`

## 動画を生成するとき

- 生成 AI の動画にするのは、湯気・手元・歩く様子のように、写真では伝わらない動きを見せたいカットだけ。数値・料金・CTA のカットは文字と図で作る
- いきなり動画を生成しない。カットごとの最初のコマを画像で作って構成の合意を取ってから、その画像を最初のコマにして動かす
- 動画生成 API は、利用者の認証情報と公式ドキュメントの手順で呼ぶ（動画生成のスクリプトは同梱していない）。
  生成した動画にも同じ形のサイドカー（`<動画ファイル名>.json`）を残す

## 守ること

- 履歴はスクリプトが自動で書く。手で書かない・書き換えない・消さない。同梱のスクリプト以外で生成したときも同じ形のサイドカーを残し、
  モデル名が結果から分からなければ `"model": "未取得"` と書く
- 失敗したのに「作りました」と書かない。使っていないモデル・ツールで作ったと書かない
- 実在の店舗・スタッフ・料理・客室を生成画像で代用しない。人物の顔を含む生成画像を「お客様の声」に使わない。
  渡された実在の写真に、写っていないものを描き足さない
- 生成画像を使ったら、成果物の説明に「生成画像である」と書く。外に渡す画像には、exiftool があれば IPTC の DigitalSourceType
  （`-XMP-iptcExt:DigitalSourceType="http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"`）も書き込む。
  無ければ「ファイルへの記録は未実施」と書く
- 生成しただけのものを、そのまま配信・投稿しない。人の確認に渡すところで止める

## 出力の型

画像（または動画）と隣のサイドカー / 選んだ経路と理由（1 行）/ 検品の結果（読んだ文字、見つけた問題、作り直した回数）/
生成画像であることの明記 / 作れなかったものがあれば、その理由と何があれば作れるか

## フォールバック先

- 生成の API キーが 1 つも無い: HTML で組んで画像にする（ここで止めない）
- ヘッドレスブラウザも無い: HTML ファイルと JSON の設計書を納品し、「画像化は未実施」と、何を入れれば進むか（Playwright か Chrome、または API キー）を書く
- 実在の写真が要るのに素材が無い: 生成で代用しない。必要な写真を一覧にして返す
- 動画生成の API キーが無い: 静止画＋動き（video-assemble）で動画にする
