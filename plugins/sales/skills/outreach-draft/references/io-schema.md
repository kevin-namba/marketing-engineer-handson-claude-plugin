# 入力と出力の列

入力も出力も 1 行 1 社。形式は CSV・スプレッドシート・貼り付けた表のどれでもよい。空欄は空欄のまま渡してよい。

## 入力

| 列 | 必須 | 内容 |
|---|---|---|
| `company_name` | 必須 | 会社・店舗名（正式名称） |
| `industry` | 推奨 | 業種 |
| `channel` | 必須 | 経路。`form`（問い合わせフォーム）/ `email` |
| `segment` | 推奨 | 区分。`cold` / `warm` / `event` / `re-engage`（既定は `cold`） |
| `contact` | 任意 | 宛名（ご担当者様 / 〇〇様） |
| `email` | email の行で必須 | 宛先のアドレス（検証済みのもの） |
| `past_contact` | 任意 | 過去の接点（なし / あり（名刺交換 2026-05）/ お断り） |
| `research_notes` | 推奨 | リサーチメモ。書き出しの根拠になる事実と観測日 |
| `urls` | 推奨 | リサーチメモの事実の出典 URL |

## 出力

| 列 | 内容 |
|---|---|
| `company_name` | 入力の会社名（照合用） |
| `channel` | form / email |
| `subject` | 件名（email だけ。form は空） |
| `subject_alt1` / `subject_alt2` | 件名の代替案 |
| `body` | 本文（プレーンテキスト。そのまま貼れる） |
| `opening_hook` | 使った書き出しの要点 |
| `evidence_case` | 引用した実績（承認済みリストのどの行か。省いたら空） |
| `cta` | 本文の依頼 |
| `personalization_source` | フックの根拠にした入力列（例: `research_notes`）。汎用なら `generic` |
| `confidence` | 高 / 中 / 低（パーソナライズの深さ） |
| `needs_review` | `true` なら人のレビュー必須 |
| `notes` | 不足しているデータ・最新の確認が要る点・レビューの観点 |

`needs_review` を `true` にする条件:

- `personalization_source` が `generic`
- リサーチメモに出典 URL が無い・観測日が古い
- 合う実績がリストに無く、実績の段落を省いた
- 区分に必要な情報が入力に無く、cold として書いた
- アドレスの検証結果が「不明」「役割アドレス」

## フォーム・メールに入れるときの対応

- フォーム: 会社名・担当者名・連絡先の欄には送り手（自社）の情報、お問い合わせ本文に `body`。件名の欄があるときだけ `subject_alt1` などから人が選ぶ
- メール: To に入力の `email`、件名に `subject`、本文に `body` ＋ 署名（送信者の名称・住所・受信拒否の連絡先）
