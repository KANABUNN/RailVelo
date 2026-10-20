# JR九州 個人用鉄道走行モニター：N02データ基盤

**門司港〜博多の32駅を対象とするSQLiteを、Windowsで実際に生成・検証した成果物です。**
N02 2025年度版を使い、元の `railmonitor_v0_2.sql` を変更せず実行し、出典・経路順序・品質管理用の `rm_` 表を追加しています。

これはMVPの地理データ基盤です。N02に基づく計算用の代表経路であり、実際の上下線・番線・転轍器・列車の進入可否を保証する線路図ではありません。

## 最初に見るもの

| ファイル | 内容 |
|---|---|
| `output/rail_jrkyushu.sqlite` | 生成済みDB。`PRAGMA user_version=2`、32駅・35駅元線形・240有向辺 |
| `output/QUALITY_REPORT.md` | 検証結果、距離比較、分岐や駅位置の未解決事項 |
| `output/review.html` | 全区間と主要箇所の図。ダブルクリックでオフライン表示可能 |
| `output/validation.json` | 30項目の機械可読な検証結果 |
| `output/stations.csv` / `station_distances.csv` | 駅順、代表距離、駅範囲、隣接駅間の形状弧長 |
| `output/corridor.geojson` | 代表経路と別経路候補の線形 |
| `output/station_lines.geojson` | 元の駅線形35件と代表経路への対応 |
| `output/nearby_excluded.geojson` | 周辺150mで見つかった別路線・別会社68地物。DB経路には不採用 |
| `output/selection_audit.csv` | 全国32,167地物の採否理由。途中まで採用した元線形も区別 |
| `data/raw/manifest.json` | 取得URL、日時、HTTP情報、サイズ、SHA-256、ZIP内部一覧 |
| `schemas/railmonitor_v0_2.sql` | 前工程の元SQL。そのまま保存 |
| `schemas/n02_extensions.sql` | 元SQLに追加する出典・品質・順序の表 |
| `scripts/` / `config/` | 再取得・抽出・生成・検証・図面出力のソースと明示設定 |
| `reports/` / `docs/` | 全国属性検査、取得確認、設計への対応、確認記録 |
| `MANIFEST.sha256` | 同梱ファイルのハッシュ（ZIP作成時に生成） |

## 得られた結果と制限

- 元の全国データは線路21,933地物、駅10,234地物。JR九州のN02路線名「鹿児島線」は線路233件・駅99件です。
- この区間は32駅ですが、門司・陣原・折尾の線形がそれぞれ2件あり、元駅地物は35件です。駅コードの重複を消さず、版付きの元レコードとアプリの32駅を分けて保存します。
- DBは118ノード、120本の計算用線形を両向きに展開した240有向辺です。117辺の代表経路と3本の別経路候補を保持しています。
- 代表経路の駅中心間は **77,552.433m**。JR九州の2024年度末資料では門司港〜小倉11.0km、小倉〜博多67.2km、計78.2km。差は約−647.567m（−0.828%）です。原因を確定できず、補正もしていません。形状弧長を営業キロと表示しないでください。
- 門司港→小倉→博多を `down`、逆を `up` とします。これは公式の方面案内と対応した区間方向です。複数の線形がある箇所で実在の上下線を同定したものではありません。
- 元データで完全に同一の頂点だけを接続します。近い点のスナップ、空白を埋める直線の生成、平面上の交差からの接続は行いません。入力の接続性だけでは実際の転轍器や運行上の接続は確定しません。
- 全採用線形は空でなく有効です。一方、N02に収録されない渡り線・個別ホーム線・細かい曲線の欠落は評価できません。貨物名義の地物の不在も、貨物列車や共用線の不在を意味しません。
- 駅範囲はN02の駅線形に由来します。`platform_begin_m/end_m` という元DDLの名前でも、実測したプラットホーム端ではありません。
- 全30検証と5件の危険ケース試験は通過。iPhoneのGPS、実走マッチング、停車判定、iOSビルド・署名は今回実施していません。

今回、有料API・商用時刻表・有料クラウドは使用していません。継続課金するサービスも作成していません。

## Windowsでオフライン再生成

Python 3.12を推奨します。Macは不要です。生成済みDBとHTMLの閲覧だけならPythonの準備も不要です。
以下はこのREADMEがあるフォルダーを開いたPowerShellで実行します。既存DBは上書きせず、別の出力フォルダーを使います。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -X utf8 scripts\build_rail_db.py --out output_rebuilt
.\.venv\Scripts\python.exe -X utf8 scripts\validate_rail_db.py output_rebuilt\rail_jrkyushu.sqlite
.\.venv\Scripts\python.exe -X utf8 scripts\make_review.py output_rebuilt
.\.venv\Scripts\python.exe -X utf8 scripts\test_topology.py
```

初回の依存パッケージ導入にはネット接続が必要です。その後は、同梱の公式ZIPと取得記録からネット接続なしで再生成できます。`.venv` は機械固有なので配布ZIPには含めません。

SQLiteのバイト一致は同じPython・SQLite・Shapely・PROJの版で確認しています。異なるOS／ランタイムでは、DBのバイト一致より検証結果と内容の一致を確認してください。DBの `built_utc` は再現性のため元ZIPの取得日時に固定し、現在時刻を埋め込みません。

## 公式データを再取得する場合

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\fetch.py --dest data\raw_recheck
```

公式2025年版カタログに掲示されたN02 ZIPのうち最新年を検出します。2026-10-20の確認では2025年版が最新版です。カタログが今後別URLへ移る場合は公式サイトで再確認してください。

元の `data/raw` を書き換えず、別フォルダーに取得してください。既存入力の内容が異なる場合は取得スクリプトが上書きを拒否します。別年版を採用するには、基準日・ライセンス・属性・駅ID対応をレビューした上で別パッケージとして更新します。別年版を2025年として誤登録する生成は拒否します。

## DBの利用契約

1. アプリの座標は `rail_edge_points` のWGS84互換経緯度を使用。索引は `rail_edge_spatial_keys` と `rail_edge_rtree` を結合します。
2. `progress_m` は**各有向辺の始点から**の非負距離。逆向きは `length_m - progress_m` に対応し、点列も逆順です。
3. 区間全体の距離は `rm_reference_path` の順序と `begin_chainage_m/end_chainage_m` を使います。門司港駅線形の中点が0、博多方向が増加。端駅範囲を含めるため始端は負、終端は博多中心距離より先まで存在します。
4. `rm_edge_metadata.role='candidate'` は別経路候補で、方向は `unknown`。代表経路と候補を区別せず列車の経路を断定しないでください。
5. `station_track_locations` の駅範囲は辺内の位置です。駅が複数辺をまたぐ場合は複数行になります。32駅の順序・代表位置は `rm_station_positions` にあります。
6. 同一N02駅コードに複数形状があり得ます。`source_station_code` はユニークキー／恒久IDにしません。アプリ駅IDは `config/station_registry.json` を維持し、将来改称時も手動対応で同じIDを残します。
7. 未確認事項は `rm_quality_issues` に残っています。`PASS_WITH_DOCUMENTED_LIMITATIONS` を実走精度の合格表示に使いません。
8. 商用時刻表・列車ID・個人GPSサンプルは入っていません。`rides` 等の元テーブルは空です。

例：駅順と形状上の累計距離を読むSQL。

```sql
SELECT s.public_name, p.sequence, p.chainage_m,
       p.extent_begin_m, p.extent_end_m, p.match_quality
FROM stations s
JOIN rm_station_positions p ON s.id=p.station_id
ORDER BY p.sequence;
```

進行方向が確定した将来のアプリで「次に通過する駅」を求める際は、この順序と現在位置を使います。「次の停車駅」は時刻表上の便が決まるまで判定できません。

## 全国展開に向けた境界

全国N02の原本を保持し、事業者・路線・区間・駅レジストリを設定として分離しています。将来は地域別にDBを生成し、版付きの元地物と永続アプリIDの対応を維持します。今回の `config` と座標投影II系は九州向けです。全国を同じ平面座標系や駅名一致だけで処理する実装にはしません。

複数路線の直通・共同駅・同名駅、異事業者間の接続、元期を伴う測地系変換、分岐の手動補正には追加設計・検証が必要です。今回のスクリプトが全国の任意区間にそのまま適用できるとは評価していません。

## 出典と再配布

出典：国土交通省「国土数値情報（鉄道データ）2025年度版」
<https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N02-2025.html>

データ基準日2025-12-31。データ固有欄の表示はCC BY 4.0です。抽出・グラフ化・代表経路選択・駅投影・距離計算を行った加工物で、国が作成した成果物ではありません。再配布時は `NOTICE.md` と出典・版・加工表示・ライセンスへのリンクを維持してください。

公式サイト一般規約には2026-03-23施行のPDL1.0の記載もあります。本パッケージはN02個別ページに明示されるCC BY 4.0を元データの条件として記録し、一般規約も取得時点の参考記録として保存しています。JR九州の照合資料をN02と同じCC BYとは扱いません。

詳細は `NOTICE.md`、`docs/DESIGN_NOTES.md`、`output/QUALITY_REPORT.md` を参照してください。
