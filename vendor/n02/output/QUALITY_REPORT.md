# N02 門司港〜博多 品質検証結果

判定：**PASS_WITH_DOCUMENTED_LIMITATIONS**。自動検証 30/30 件。物理的な分岐の接続可否・実走受入は未確認です。

32駅、元の駅線形35件、ノード118件、計算用の有向辺240件、代表経路117辺。
門司港中心〜博多中心のGRS80弧長：77552.433 m。全端駅範囲を含む代表経路：77787.401 m。

## 検証結果

| 検証 | 結果 |
|---|---|
| sqlite_integrity | PASS |
| foreign_keys | PASS |
| schema_version | PASS |
| original_v0_2_schema_unchanged | PASS |
| source_archive_hash | PASS |
| Station_source_crs | PASS |
| RailroadSection_source_crs | PASS |
| source_features_exactly_preserved | PASS |
| operator_line_and_railway_type_filter | PASS |
| selected_geometry_valid_and_nonempty | PASS |
| finite_numeric_values | PASS |
| progress_indices_and_positive_lengths | PASS |
| ellipsoid_distance_recomputed | PASS |
| exact_edge_node_endpoints | PASS |
| reverse_virtual_edges | PASS |
| no_fabricated_gap_geometry | PASS |
| rtree_complete_outward_bounds | PASS |
| continuous_ordered_reference_path | PASS |
| official_station_order_and_count | PASS |
| station_chainage_monotonic | PASS |
| center_distance_equals_reference | PASS |
| station_extent_bounds | PASS |
| all_stations_have_graph_locations | PASS |
| all_35_station_line_variants_retained | PASS |
| no_fabricated_rides | PASS |
| no_fabricated_gps_samples | PASS |
| no_fabricated_match_results | PASS |
| no_fabricated_station_events | PASS |
| commercial_timetable_absent | PASS |
| limitations_persisted | PASS |

## 営業キロとの独立比較

[JR九州 2024年度末 線区別ご利用状況](https://www.jrkyushu.co.jp/company/info/data/pdf/2024senku.pdf) 1ページ目の2区間を照合。合計は両区間の和です。差の原因は未確定で、較正は行っていません。

| 始駅 | 終駅 | 営業キロ km | N02形状 m | 差 m | 差 % |
|---|---|---:|---:|---:|---:|
| 門司港 | 小倉 | 11.0 | 10871.707 | -128.293 | -1.166 |
| 小倉 | 博多 | 67.2 | 66680.726 | -519.274 | -0.773 |
| 門司港 | 博多 | 78.2 | 77552.433 | -647.567 | -0.828 |

## N02の限界と処理結果

- 元属性は `N02_003=鹿児島線`、`N02_004=九州旅客鉄道`、`N02_001=11`、`N02_002=2`。運行上の呼び名「鹿児島本線」への対応は明示設定。直通する列車の系統・列車ID・停車駅はこの属性からは決まらない。
- 駅順32駅はJR九州公式の路線別駅一覧に照合。門司港→小倉→博多を下りとする方向は公式駅案内で確認。GPSから進行方向を推定する処理は今回の対象外。
- 門司・陣原・折尾は同じ駅コードでも駅線形が複数ある。35件すべての元属性・元形状を保存し、32駅のアプリIDとは別に管理する。折尾の異なる線形の用途や現行ホームとの対応を推測しない。
- 原線形の同一頂点だけを接続。スナップ、直線の補間による穴埋め、平面上の交点からの接続は0件。入力の接続性は地図表現上のもので、転轍器・進入方向・列車の通行可否の証明にはならない。
- 代表経路は距離計算のために最短経路を明示的に選択したもの。別経路候補もDBに残し `direction=unknown` とする。上下方向の仮想辺は実在する上下線を意味しない。
- 採用した線形にnull/空/不正幾何はない。全駅代表点に元線形上の経路を確保。これは現実の線路形状が欠けていないという評価ではない。N02で表現されない渡り線・ホーム別線路・細かなカーブの欠落は判定不能。
- 周辺150mの別事業者・別路線68地物は別ファイルで保存し、DBの経路には取り込まない。JR貨物名義の地物が見つからなくても、貨物の走行・共用線が存在しない証拠にはならない。N02の対象は旅客鉄道・軌道。
- `platform_begin_m/end_m` はN02駅線形に基づく範囲。実ホーム端・停止位置・扉開時刻との一致は未確認。端駅の範囲を欠かさないよう代表経路は駅中心より外側まで保持する。
- 距離は平面の緯度経度差や駅間直線距離ではなく、GRS80楕円体上の各線分長の和。営業キロへ較正していない。駅中心もN02駅線形の長さ中点という便宜的な定義。
- JGD2011→WGS84はPROJの静的変換（公称精度1m、今回のパイプラインはno-op）。地殻変動・観測元期・GNSSの時刻依存変換は扱っていない。線路番号レベルの測位精度を主張しない。

## 別経路候補（実際の通行可否は未確認）

| 辺（逆向きも保存） | 弧長 m | 元地物 |
|---|---:|---|
| e0002.f | 383.447 | ["RailroadSection:02929"] |
| e0052.f | 1109.838 | ["RailroadSection:02915"] |
| e0078.f | 871.634 | ["RailroadSection:02881"] |

## 個別の要確認事項

### Q0001 REFERENCE_NOT_SURVEYED_RUNNING_TRACK

関連地物：

```json
{
  "message": "N02線形による計算用代表経路。上下線・番線・転轍器・接続可否を保証しない。最短経路は実際の乗車経路の同定ではない。"
}
```

### Q0002 MULTIPLE_STATION_LINE_FEATURES

関連地物：Station:01467, Station:01475

```json
{
  "station": "門司",
  "representatives": [
    {
      "source_id": "Station:01467",
      "station_id": "aed40e40-8da5-5717-8138-afa1c0bf478a",
      "public_name": "門司",
      "sequence": 2,
      "chainage_m": 5391.194632335713,
      "offset_m": 0.0,
      "extent_begin_m": 5225.292630649304,
      "extent_end_m": 5557.096746210563,
      "on_candidate_graph": true
    },
    {
      "source_id": "Station:01475",
      "station_id": "aed40e40-8da5-5717-8138-afa1c0bf478a",
      "public_name": "門司",
      "sequence": 2,
      "chainage_m": 5391.089537817323,
      "offset_m": 33.229295245102364,
      "extent_begin_m": 5226.719958238614,
      "extent_end_m": 5555.536773315439,
      "on_candidate_graph": false
    }
  ],
  "message": "同一駅の複数線形を保存。位置・用途・現行番線との対応はN02だけでは確定できない。"
}
```

### Q0003 STATION_VARIANT_NOT_ON_THROUGH_GRAPH

関連地物：Station:01475

```json
{
  "station": "門司",
  "reference_offset_m": 33.229295245102364,
  "message": "鹿児島線属性の通り抜け経路に載らない駅線形。代表経路へ接続線を補作しない。"
}
```

### Q0004 MULTIPLE_STATION_LINE_FEATURES

関連地物：Station:01469, Station:01471

```json
{
  "station": "陣原",
  "representatives": [
    {
      "source_id": "Station:01469",
      "station_id": "4b0b6d8a-473d-5e32-8125-153ba94ed1de",
      "public_name": "陣原",
      "sequence": 11,
      "chainage_m": 26367.62339750753,
      "offset_m": 0.0,
      "extent_begin_m": 26307.475702635784,
      "extent_end_m": 26427.771027826577,
      "on_candidate_graph": true
    },
    {
      "source_id": "Station:01471",
      "station_id": "4b0b6d8a-473d-5e32-8125-153ba94ed1de",
      "public_name": "陣原",
      "sequence": 11,
      "chainage_m": 26368.844328680214,
      "offset_m": 22.184379001604146,
      "extent_begin_m": 26309.054963320923,
      "extent_end_m": 26428.489141206046,
      "on_candidate_graph": false
    }
  ],
  "message": "同一駅の複数線形を保存。位置・用途・現行番線との対応はN02だけでは確定できない。"
}
```

### Q0005 STATION_VARIANT_NOT_ON_THROUGH_GRAPH

関連地物：Station:01471

```json
{
  "station": "陣原",
  "reference_offset_m": 22.184379001604146,
  "message": "鹿児島線属性の通り抜け経路に載らない駅線形。代表経路へ接続線を補作しない。"
}
```

### Q0006 MULTIPLE_STATION_LINE_FEATURES

関連地物：Station:01461, Station:01464

```json
{
  "station": "折尾",
  "representatives": [
    {
      "source_id": "Station:01461",
      "station_id": "f72e25db-0567-5775-af9e-8f7e821630ff",
      "public_name": "折尾",
      "sequence": 12,
      "chainage_m": 29229.32243864942,
      "offset_m": 39.87342081441309,
      "extent_begin_m": 29199.623476554658,
      "extent_end_m": 29257.960437835627,
      "on_candidate_graph": false
    },
    {
      "source_id": "Station:01464",
      "station_id": "f72e25db-0567-5775-af9e-8f7e821630ff",
      "public_name": "折尾",
      "sequence": 12,
      "chainage_m": 29546.062498775296,
      "offset_m": 0.0,
      "extent_begin_m": 29431.617316917444,
      "extent_end_m": 29660.507708207857,
      "on_candidate_graph": true
    }
  ],
  "message": "同一駅の複数線形を保存。位置・用途・現行番線との対応はN02だけでは確定できない。"
}
```

### Q0007 STATION_VARIANT_NOT_ON_THROUGH_GRAPH

関連地物：Station:01461

```json
{
  "station": "折尾",
  "reference_offset_m": 39.87342081441309,
  "message": "鹿児島線属性の通り抜け経路に載らない駅線形。代表経路へ接続線を補作しない。"
}
```

### Q0008 DIFFERENCE_FROM_OFFICIAL_OPERATING_KM

関連地物：

```json
{
  "source": {
    "source_url": "https://www.jrkyushu.co.jp/company/info/data/pdf/2024senku.pdf",
    "source_reference": "2024年度末 線区別ご利用状況、PDF 1ページ目の在来線（幹線）",
    "segments": [
      {
        "from": "門司港",
        "to": "小倉",
        "operating_km": 11.0
      },
      {
        "from": "小倉",
        "to": "博多",
        "operating_km": 67.2
      }
    ]
  },
  "comparisons": [
    {
      "from": "門司港",
      "to": "小倉",
      "operating_km": 11.0,
      "n02_reference_m": 10871.706546245498,
      "difference_m": -128.29345375450248,
      "difference_percent": -1.166304125040929
    },
    {
      "from": "小倉",
      "to": "博多",
      "operating_km": 67.2,
      "n02_reference_m": 66680.72636605153,
      "difference_m": -519.2736339484691,
      "difference_percent": -0.7727286219471274
    },
    {
      "from_station": "門司港",
      "to_station": "博多",
      "operating_km": 78.2,
      "n02_reference_m": 77552.43291229702,
      "difference_m": -647.567087702977,
      "difference_percent": -0.828090904991019
    }
  ],
  "message": "形状弧長と営業キロには差がある。原因・現在の実走距離との誤差は確定できない。値の較正・引伸しは行っていない。"
}
```

### Q0009 SOURCE_GRAPH_JUNCTION_UNVERIFIED

関連地物：RailroadSection:02928, RailroadSection:02929, RailroadSection:02938, Station:01500

```json
{
  "longitude": 130.4206,
  "latitude": 33.591,
  "degree": 3,
  "message": "元データで同一頂点を共有する分岐候補。実際の線路接続・立体交差・進入方向は未確認。"
}
```

### Q0010 SOURCE_GRAPH_JUNCTION_UNVERIFIED

関連地物：RailroadSection:02918, RailroadSection:02928, RailroadSection:02929

```json
{
  "longitude": 130.42098,
  "latitude": 33.59441,
  "degree": 3,
  "message": "元データで同一頂点を共有する分岐候補。実際の線路接続・立体交差・進入方向は未確認。"
}
```

### Q0011 SOURCE_GRAPH_JUNCTION_UNVERIFIED

関連地物：RailroadSection:02901, RailroadSection:02906, RailroadSection:02915

```json
{
  "longitude": 130.60463,
  "latitude": 33.8186,
  "degree": 3,
  "message": "元データで同一頂点を共有する分岐候補。実際の線路接続・立体交差・進入方向は未確認。"
}
```

### Q0012 SOURCE_GRAPH_JUNCTION_UNVERIFIED

関連地物：RailroadSection:02904, RailroadSection:02906, RailroadSection:02915

```json
{
  "longitude": 130.60873,
  "latitude": 33.82756,
  "degree": 3,
  "message": "元データで同一頂点を共有する分岐候補。実際の線路接続・立体交差・進入方向は未確認。"
}
```

### Q0013 SOURCE_GRAPH_JUNCTION_UNVERIFIED

関連地物：RailroadSection:02871, RailroadSection:02881, RailroadSection:02897

```json
{
  "longitude": 130.76097,
  "latitude": 33.86656,
  "degree": 3,
  "message": "元データで同一頂点を共有する分岐候補。実際の線路接続・立体交差・進入方向は未確認。"
}
```

### Q0014 SOURCE_GRAPH_JUNCTION_UNVERIFIED

関連地物：RailroadSection:02881, RailroadSection:02882, RailroadSection:02884

```json
{
  "longitude": 130.77032,
  "latitude": 33.86712,
  "degree": 3,
  "message": "元データで同一頂点を共有する分岐候補。実際の線路接続・立体交差・進入方向は未確認。"
}
```

## 今回完了した範囲

取得・抽出・計算用グラフ・双方向の辺・駅範囲・距離・SQLite・自動検証・オフライン図面生成をWindows上で実行。元のSQLの定義を変更せず、出典と品質管理の表を追加。

## 未完・受入が必要な範囲

実際の分岐・番線対応の現地／一次図面照合、各隣接駅間の営業キロとの全数照合、距離差の原因特定、乗車GPSによるマップマッチング、到着・通過判定、iOSビルド・実機試験。自動検証PASSをこれらの完了と解釈しない。

## 出典・利用条件

[国土交通省 N02 鉄道2025年度版](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N02-2025.html)、基準日2025-12-31、CC BY 4.0。出典、版、加工内容、ライセンスを同梱DBとNOTICEに表示。

[JR九州 路線別駅一覧](https://www.jrkyushu-timetable.jp/sp/railway_list.html)、[門司港 方面案内](https://www.jrkyushu-timetable.jp/cgi-bin/sp/sp-tt_list.cgi/28345)で駅順と下り方向を確認。時刻表の時刻・列車データは取得・保存していない。
