# 画像・動画の生成 API を使うときの注意

どれも執筆時点の仕様。組み込む前・エラーが出たときは、公式ドキュメントで確認する。

- Gemini の画像生成: https://ai.google.dev/gemini-api/docs/image-generation
- OpenAI の画像生成: https://developers.openai.com/api/docs/guides/image-generation
- Veo（動画）: https://ai.google.dev/gemini-api/docs/veo

## 2 つの API の違い

| | Gemini 系 | OpenAI 系（GPT Image） |
|---|---|---|
| 大きさの指定 | 比率（`--aspect 16:9`）＋解像度ティア（`--size 2K`） | ピクセル（`--size 1536x1024`）。比率では指定できない |
| 参照画像 | 同じ経路に画像を足す | 別のエンドポイント（編集用）。マスクで部分修正ができる |
| 認証情報 | `GEMINI_API_KEY` | `OPENAI_API_KEY` |

- 使える比率・解像度・背景の透過はモデルごとに違う。エラーの本文を読んで直す
- API キーは用途ごとに確かめる。モデル名はあちこちに書かず、環境変数の 1 か所で持つ

## サイドカーの形

```json
{
  "id": "cr_0193",
  "file": "yoyaku3d_after_catch_meta_1080x1080_v02.png",
  "appeal": "yoyaku3d",
  "copy_type": "after",
  "layout_type": "catchcopy",
  "placement": "meta_feed",
  "size": "1080x1080",
  "variant_of": "cr_0187",
  "changed": ["copy"],
  "generation": {
    "provider": "gemini",
    "model": "gemini-3.1-flash-image",
    "prompt": "朝もやの山あい、紅葉の木立、朝日、建物と人物なし、写真、広角",
    "params": {"aspect_ratio": "1:1", "image_size": "2K"},
    "created_at": "2026-09-17T02:10:44Z"
  }
}
```

`generation` の欄はスクリプトが書く。編集したときは編集元が `edited_from` に残る。

## 同梱スクリプトの結果の読み方

| 結果 | 意味 | 次にやること |
|---|---|---|
| `"ok": true` と `files` | 画像とサイドカーが書かれた | 画像を開いて全文字を読む |
| `"error"` に「未設定」 | その提供元の API キーが無い | もう一方の提供元 → HTML の順に切り替える |
| `"error"` に「モデルが見つかりません」 | モデルが入れ替わった | 公式ドキュメントで現行のモデル名を確かめ、環境変数か `--model` で指定する |
| `"error"` に「画像が含まれていません」 | 安全フィルタ・モデレーションで止まった可能性 | プロンプトを言い換える。実在の人物・商標に当たる表現を外す |
| `"error"` に「レート上限」 | 上限か残高の不足 | 時間を置くか、別の経路で作る |

## 動画生成 API の注意

- 対応する比率・秒数・解像度は公式ドキュメントで確認する。最初のコマを画像で指定できる
- 生成には時間がかかる（1 本で十数分かかることがある）。本数と見込み時間を先に伝えてから始める
- 生成した動画の URL が短時間で使えなくなる提供元がある。受け取ったその場でダウンロードして自分の保管場所に置く
- 待ち時間の上限で打ち切っても、提供元の側の処理は続いていることがある。出し直す前に処理の状態を確かめる
