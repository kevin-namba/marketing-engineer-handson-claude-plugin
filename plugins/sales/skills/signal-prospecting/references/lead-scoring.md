# リードスコア（営業に渡す順番）

検知したリードを営業に渡す前の処理。生成 AI の判断ではなく、同じ入力からは必ず同じ結果が出る処理で行う。

## 重複排除と除外

- キーは**法人名＋ドメイン**。何度実行しても同じキーの行が増えないようにする。
- 既存のお客様・アプローチ済みの相手・お断りを受けた相手は除外リストに入れ、リストを作るたびに適用する。送信の直前にももう一度確認する。
- CRM への登録は、登録の案を出して人が確認してから反映する。

## リードスコアは足し算で出す

材料は 3 種類。ICP への適合（業種・規模・地域）、シグナルの温度（高・中・低と観測からの経過日数）、こちらへの反応（返信・資料の閲覧・フォームの送信）。

- 重みは設定の 1 箇所に置く。点数は足し算だけで出し、掛け算や例外の分岐を入れない。
- 閾値以上の行だけを営業に渡す。未満の行はフォローアップで育成する。
- 重みを変えたら日付と理由を記録する。

重みの設定（`lead_score.py` が読む JSON）:

```json
{
  "handoff_threshold": 60,
  "signal_expire_days": 30,
  "rules": [
    {"group": "fit", "label": "業種が対象", "column": "industry", "op": "in", "value": ["宿泊", "飲食", "美容"], "points": 20},
    {"group": "fit", "label": "店舗数が 1〜10", "column": "store_count", "op": "between", "value": [1, 10], "points": 10},
    {"group": "signal", "label": "温度 高", "column": "temperature", "op": "eq", "value": "高", "points": 30},
    {"group": "signal", "label": "温度 中", "column": "temperature", "op": "eq", "value": "中", "points": 15},
    {"group": "signal", "label": "温度 低", "column": "temperature", "op": "eq", "value": "低", "points": 5},
    {"group": "engagement", "label": "返信があった", "column": "replied", "op": "truthy", "points": 25},
    {"group": "engagement", "label": "料金ページを見た", "column": "viewed_pricing", "op": "truthy", "points": 10}
  ]
}
```

- 数値はすべて例。自社の受注データから決める（受注と失注で差が出た属性だけを適合の項目に採用する）。
- `group` が `signal` のルールは、`observed_at` 列（観測日）から `signal_expire_days` を過ぎた行には加点しない。
- 使える `op` は `eq` / `in` / `between` / `gte` / `lte` / `truthy` / `contains`。値が空の列は加点せず、内訳に「未取得」と出す（0 として扱わない）。
