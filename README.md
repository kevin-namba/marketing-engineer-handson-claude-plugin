# マーケティングエンジニア入門 ハンズオン用 plugin

『マーケティングエンジニア入門』の本文で扱う Skill を、章ごとの Claude Code plugin にまとめたものです。ハンズオンで読みながら動かせるように、Skill は本に載せた簡略版に近い短さに揃え、動かすのに要る出力テンプレートとスクリプトだけを足しています。

ライセンスは FSL-1.1-ALv2 です。社内での利用や学習には自由に使えますが、同等の商用サービスとしての提供はできません（詳しくは[ライセンス](#ライセンス)）。

## 導入

```bash
# Claude Code の中で
/plugin marketplace add trip-clear/marketing-engineer-handson-claude-plugin
/plugin install strategy@marketing-engineer-handson   # 使う章の plugin を入れる
```

手元に clone した場合は `/plugin marketplace add <clone したフォルダのパス>` で追加できます。入れたあと `/skills` を開き、一覧に名前が出ていることを確かめてください。Skill は `/strategy:media-selection` のように `plugin名:Skill名` で直接呼び出せます。

## 収録している plugin

| plugin | 対応する章 | Skill | サブエージェント |
|---|---|---|---|
| `strategy` | 第3章 戦略設計を自動化する | 9 | 0 |
| `creative` | 第4章 クリエイティブ作成を自動化する | 12 | 1 |
| `ads` | 第5章 広告運用を自動化する | 9 | 0 |
| `seo-llmo` | 第6章 SEO/LLMO を自動化する | 6 | 0 |
| `sales` | 第9章 営業活動を自動化する | 16 | 1 |

## 使う前に

- **データの取り方はフォールバックの順で書いてあります。** 媒体の MCP ツール（つないである場合）→ 公式 API / 公式 CLI → 管理画面から出した CSV → 利用者が貼った数字、の順に試し、どれも無ければ「未取得」と書いて対処法を添えます。MCP ツールが 1 つも無い環境でも、CSV を渡せば動きます。
- **外部に反映される操作は、実行前に人の確認を通します。** 投稿・配信開始・予算変更・送信が対象です。Claude Code の `settings.json` の `permissions`で、該当するツールを `ask` にしておいてください。
- **スクリプトは単体で動きます。** ほとんどは Python の標準ライブラリだけで動き、追加のパッケージや外部コマンド（ffmpeg など）が要るものは、その Skill の SKILL.md に書いてあります。API キーが要るスクリプトは、環境変数から読みます。
- **仕様や数字は執筆時点のものです。** 媒体の API・審査・上限は変わるので、実行前に公式ドキュメントで確認してください。

## Skill の一覧

### strategy（第3章 戦略設計を自動化する）

- `brand-knowledge-from-url`: 会社やサービスのサイト URL から、ブランドナレッジ（事業・主要ターゲット・提供価値・トンマナ）を作る
- `brand-listening`: ブランド・店舗の口コミや言及を、Googleマップ・予約/グルメサイト・X・Instagram・TikTok・Web 記事から定点で集め、前回との差と要対応をまとめる
- `growth-experiment`: 打ち手に効果があったかをテストで確かめる
- `market-position-analysis`: 商材の 3C 分析（Customer/Competitor/Company）から SWOT・KBF・KSF・ポジショニングマップ・WHO/WHAT/WHY/HOW の訴求軸まで整理する
- `media-selection`: 運用型広告の媒体選定
- `monthly-channel-review`: チャネル横断の定例レポート
- `research-channel-routing`: 情報収集のツールを目的ごとに決めるチャネルルーティング表
- `single-customer-deep-dive`: 実在の顧客 1 人の行動と心理から、便益と独自性の組み合わせを見つける（N1 分析）
- `trend-watch`: いま話題のトレンドを見つけ、ブランドが便乗してよいかを判定してから、投稿案にする

### creative（第4章 クリエイティブ作成を自動化する）

- `ad-copy`: 広告のキャッチコピーを型で量産する
- `banner-design`: 静止画バナーの構成を設計し、画像化と検品まで行う
- `image-video-gen`: 画像と動画を生成する
- `landing-page-builder`: 広告の遷移先 LP を、設計書 → 単体 HTML → 画像 → 計測タグ → 検証の順で作る
- `lp-improve`: 既存の LP を、1 か所だけ変えた案を作り、テストの結果に合わせて直す
- `lp-measurement-tags`: LP に GA4・Meta ピクセル・Google タグマネージャー（GTM）の計測タグを入れ、 申し込みボタンを押してデータが送られるかまで確かめる
- `offer-design`: 特典・体験・保証・限定・価格の見せ方そのものを設計する
- `reel-script`: たて型のショート広告の台本を書く
- `reel-teardown`: 参考にする短尺動画を分解し、台本・構成・絵コンテを起こす
- `storyboard`: 動画広告の編集依頼書（絵コンテ）を作る
- `video-assemble`: 絵コンテ（編集依頼書）を受け取って動画を組み、検品して納品する
- `video-production`: 広告動画・紹介動画を作るときの最初の入口
- `storyboard-designer`（サブエージェント）

### ads（第5章 広告運用を自動化する）

- `ad-cycle`: 配信中の広告の周回を回す
- `ad-operation`: 広告の出稿を、与件把握からレポートまで工程ごとの Skill へ渡しながら進める
- `ad-patrol`: 配信中の広告を巡回する
- `ad-weekly-report`: 広告媒体の実績を取得し、週次・月次の広告レポートを作る
- `cpa-budget-plan`: 案件の目標 CPA・撤退ライン・テスト期間の予算・日予算を、客単価と粗利から計算して決める
- `keyword-volume`: キーワードの実検索ボリューム・クリック単価・広告の競合性を取る
- `meta-ads-api`: Meta 広告（Facebook / Instagram）のキャンペーン・広告セット・広告・素材を 取得・作成・更新し、実績を取る
- `meta-ads-playbook`: Meta 広告の設計と運用判断
- `weekly-ad-tuning`: 配信中の広告の直近の実績を取得し、「触らない / 入札を変える / 予算を変える / クリエイティブを差し替える / 止める」のどれにするかを広告セットごとに提案する

### seo-llmo（第6章 SEO/LLMO を自動化する）

SEO の Skill は「入口 1 つ + 分類」の 6 本です。作業ごとの手順は、それぞれの SKILL.md に節として書いてあります（本文の骨子 1 つが 1 節）。API の呼び出し方や点検表のように節に収まらないものだけ `references/` に置いています。この plugin はスクリプトを同梱しておらず、Claude Code の標準のツールだけで動きます。

- `seo`: SEO の入口。SEO 改善の全工程・サイト全体の監査・どの段で詰まっているかの判定・週次の改善サイクルを受け持ち、個別の作業は分類の Skill へ渡す
- `seo-technical`: テクニカル。ページ診断・変更の見張り・構造化データ・サイトマップ・多言語ページ・画像の最適化・商品ページ・まとめて生成するページ
- `seo-content`: コンテンツ。キーワードの選定・上位ページの種類判定・トピックのまとめ方・記事制作の全工程（構成・ブリーフ・執筆・文体・レビュー）・比較ページ・リライト指示書・ページ品質の点検・検索体験の点検・上位ページとの比較
- `seo-backlinks`: 被リンク。参照ドメイン・アンカーテキスト・有害なリンク・競合との差を、無料の取得元を信頼度で重み付けしてまとめる
- `seo-measurement`: 計測。検索実績の取得・流入の分析・検索順位の計測・表示速度の計測
- `ai-search-optimization`: AI の回答での可視性（AIO / GEO / LLMO）の診断と改善、クエリファンアウトの網羅確認、言及の定点計測

### sales（第9章 営業活動を自動化する）

- `call-prep`: 商談の前に、CRM の経緯と Web の直近情報から 1 画面のブリーフを作る
- `call-summary`: 商談のメモや文字起こしから、社内サマリー・顧客向けフォローアップ・CRM の更新案の 3 つを作る
- `case-research`: 与件（相手の課題）を起点に、他社の事例と自社の実績を両方集め、 再現できるかを付けて提案材料にする
- `company-brief`: 初めて連絡する前に、見込み客の企業・店舗・人物を調べて 1 本のレポートにする
- `competitor-battlecard`: 相見積りや乗り換えの商談で、競合（他社・代替手段・内製）を公開情報で調べ、自社との比較表と 競合ごとのカード（強み・弱み・料金・話し方・質問）にまとめる
- `daily-briefing`: CRM と議事録から、今日の最優先 1 件・数字・会議と会議前の一手・アラート・推奨アクション 3 つを 2 分で読める 1 通にまとめる
- `event-scouting`: 出展・登壇・出演の機会を発掘し、登壇提案書まで作る
- `forecast`: 開いている商談の確度 × 単価 × 期間の加重和で、ベスト・想定・ワーストの売上予測と 目標に対するギャップを出す
- `outreach-copy`: 1 行 1 社のデータから、そのまま貼れる営業文面を一括で生成する
- `outreach-draft`: 企業調査の結果から相手の事実を 1 つ選び、それを根拠にした初回の営業文面（フォーム・メール）と 3 / 7 / 14 日目のフォローを書く
- `pipeline-review`: 開いている商談の一覧を 4 つの観点と固定の閾値で見直し、今週注力する案件・リスクの一覧・ データの欠け・削除候補を出す
- `pr-outreach`: プレスリリースの原稿と、掲載を打診するメディアのリスト、掲載後の実測までを扱う
- `proposal-workflow`: 提案資料づくりの全工程（与件把握 → 企業調査 → 事例調査 → 施策の熟考 → ストーリー構築 → 提案概要の登録と承認 → 資料作成 → 品質チェックと商談準備）を、工程ごとの Skill に受け渡して回す
- `quote`: 見積書を表計算ファイルと PDF の両方で作り、クライアント別のフォルダに保存する
- `signal-prospecting`: 公開の投稿や情報から「いま探している・困っている」見込み客の兆しを拾い、 根拠付きのリード一覧と返信の下書きを作る
- `tender-scouting`: 自治体・観光協会・公共団体の公募（プロポーザル・入札）を巡回し、 自社の資産との適合度でランク付けした応募先の一覧を作る
- `proposal-strategist`（サブエージェント）

## 構成

```
.claude-plugin/marketplace.json     マーケットプレイスの定義
plugins/<plugin>/.claude-plugin/plugin.json
plugins/<plugin>/skills/<Skill 名>/SKILL.md
plugins/<plugin>/skills/<Skill 名>/references/   出力テンプレートなど（SKILL.md から必要なときに読む。無い Skill もある）
plugins/<plugin>/skills/<Skill 名>/scripts/      集計・検算・検証のスクリプト
plugins/<plugin>/agents/<名前>.md                サブエージェントの定義
```

## ライセンス

[Functional Source License, Version 1.1, ALv2 Future License](LICENSE)（FSL-1.1-ALv2）で提供しています。

- 社内での利用や、非商用の教育・研究には、申請なしで使えます。
- この Skill 群やその改変版を、同じか近い機能を持つ商用の製品・サービスとして第三者に提供すること（Competing Use）はできません。この Skill 群を使った研修や導入支援を商用で提供したいなど、当たるかどうか迷う場合は[お問い合わせ](https://tripclear.jp/#contact)ください。
- 各バージョンは、公開した日から 2 年が経つと Apache License, Version 2.0 のもとでも使えるようになります。

Pull Request は受け付けていません。理由は [CONTRIBUTING.md](CONTRIBUTING.md) にあります。
