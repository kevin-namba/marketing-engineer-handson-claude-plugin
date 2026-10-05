# サイトマップの送信

> `seo-technical` の SKILL.md「サイトマップ」の節の手順 6〜9 から読む。
> 送信は取り消せない外部への反映なので、点検が済んでから、人の確認を通して行う。

## 送信先を選ぶ

1 回の送信で全部の検索エンジンには届かない。検索エンジンごとに送り方が違う。

| 経路 | 送信先 | 使いどころ | 注意 |
|---|---|---|---|
| Search Console のサイトマップ送信 | Google | サイト全体のサイトマップを出す・中身を更新したことを知らせる | 送信の成功は「受理された」まで。読み込まれたかは後で確かめる |
| IndexNow | Bing・Naver・Seznam・Yandex など参加しているエンジン | 追加・更新・削除した URL を知らせる | Google は参加していない。所有確認の鍵ファイルをサイトに公開しておく |
| Indexing API | Google | 求人（JobPosting）と配信イベント（BroadcastEvent）のページだけ | 一般の記事には使わない（公式が用途を限定している） |

一般の記事を Google に早く読ませたいときは、サイトマップを更新して送信し、管理画面の URL 検査から
インデックス登録をリクエストする（URL 検査の登録リクエストは API に無い。人が管理画面で行う）。

## Search Console への送信

出典: [Sitemaps: submit](https://developers.google.com/webmaster-tools/v1/sitemaps/submit) /
[Sitemaps リソース](https://developers.google.com/webmaster-tools/v1/sitemaps)

| メソッドと URL | 内容 |
|---|---|
| `PUT https://www.googleapis.com/webmasters/v3/sites/{siteUrl}/sitemaps/{feedpath}` | 送信。成功すると本文は空で返る |
| `GET …/sitemaps/{feedpath}` | 1 件の状態（送信後の確認に使う） |
| `GET …/sitemaps` | 送信済みのサイトマップの一覧 |

- `siteUrl` は Search Console のプロパティの文字列そのもの（`sc-domain:example.com` か `https://example.com/`）。一覧から選ぶ
- `feedpath` はサイトマップの絶対 URL
- 必要なスコープは `https://www.googleapis.com/auth/webmasters`（読み取り専用の `webmasters.readonly` では送れない）

[search-console-mcp](https://github.com/trip-clear/search-console-mcp) を使う場合のツール:

| ツール | 種類 | パーミッション |
|---|---|---|
| `sitemaps_list` / `sitemaps_get` | 読み取り | allow |
| `sitemaps_submit` | 送信（変更系） | **ask** |
| `sitemaps_delete` | 削除（変更系） | **ask** |

`GSC_READONLY=1` で起動していると変更系のツールは出てこない。そのときは送信せず、管理画面での送信手順
（「インデックス作成 > サイトマップ」にサイトマップの URL を入れて送信）を書いて渡す。

### 送信後に読む項目（`sitemaps_get`）

| 項目 | 読み方 |
|---|---|
| `lastSubmitted` | 今回の送信日時になっているか |
| `isPending` | `true` ならまだ処理されていない。時間を置いて読み直す |
| `lastDownloaded` | Google が最後に読み込んだ日時。送信より前のままなら、まだ読まれていない |
| `errors` | サイトマップそのものの誤り。0 でなければ直してから送り直す |
| `warnings` | 中の URL の軽い問題。件数と内容を報告する |
| `contents[].submitted` | 種類ごとの送信件数。点検で数えた件数と食い違えば報告する |

送信直後は `isPending` が `true` のことが多い。数分〜数時間たってから読み直し、
`lastDownloaded` と `errors` を確かめた時点で「送信済み」と書く。

## IndexNow での通知

出典: [IndexNow のドキュメント](https://www.indexnow.org/documentation) /
[Bing の IndexNow の手引き](https://www.bing.com/indexnow/getstarted)

1. 鍵を決める（英数字とダッシュで 8〜128 文字）
2. 鍵ファイルを公開する。既定はサイトのルートの `https://{host}/{key}.txt` で、中身は鍵の文字列だけ（UTF-8）。
   別の場所に置くなら送信時に `keyLocation` で指す（その場所より下の URL しか送れない）
3. **送る前に鍵ファイルを実際に取得し、200 で鍵の文字列が返ることを確かめる**
4. `POST https://api.indexnow.org/indexnow`（`Content-Type: application/json; charset=utf-8`）で送る

```json
{
  "host": "www.example.com",
  "key": "<鍵>",
  "keyLocation": "https://www.example.com/<鍵>.txt",
  "urlList": [
    "https://www.example.com/plan/family/",
    "https://www.example.com/blog/kids-onsen/"
  ]
}
```

- 1 回の POST で送れるのは 10,000 URL まで
- 送るのは、追加・更新・削除した URL だけ。導入前の古い変更をまとめて送らない
- 参加しているエンジンには、1 回の送信で共有される（エンジンごとに送り直さない）

| 応答 | 意味 | 次にすること |
|---|---|---|
| 200 | 受け付けた | 送信済みとして記録する |
| 202 | 受け取った。鍵の確認はまだ | 送信済みとして記録し、「鍵の確認待ち」と添える |
| 400 | 形式が不正 | 本文を直す。自動で送り直さない |
| 403 | 鍵が無効（鍵ファイルが無い・中身が違う） | 鍵ファイルの公開を確かめる |
| 422 | URL が host に属していない、または鍵の形式が違う | `urlList` と `host` を突き合わせる |
| 429 | 送りすぎ | 時間を置く。続けて送らない |

IndexNow に送っても、クロールやインデックスは保証されない。

## パーミッションの設定（概念例）

```json
{
  "permissions": {
    "allow": [
      "mcp__search-console__query",
      "mcp__search-console__inspect",
      "mcp__search-console__sites_list",
      "mcp__search-console__sitemaps_list",
      "mcp__search-console__sitemaps_get"
    ],
    "ask": [
      "mcp__search-console__sitemaps_submit",
      "mcp__search-console__sitemaps_delete",
      "mcp__search-console__sites_add",
      "mcp__search-console__sites_delete",
      "mcp__seo_writer__indexnow_submit"
    ]
  }
}
```

- サーバー名（`search-console`）は登録したときに付けた名前に置き換える。`seo_writer` は IndexNow の送信を
  包むために自分で作った MCP サーバーの概念例
- IndexNow を Bash の `curl` で送らせると、パーミッションはツール名で効くので確認が出ない。送信は専用のツールにして ask に書く
- ルーティン（クラウドで動く定期実行）では確認画面が出ず、ask のツールも確認なしで実行される。
  送信のツールを持つコネクターはルーティンに含めない
