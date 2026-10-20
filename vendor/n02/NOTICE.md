# 出典・ライセンス・加工表示

## N02元データと加工データ

出典：国土交通省「国土数値情報（鉄道データ）2025年度版」

- 個別ページ：<https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N02-2025.html>
- 公式ZIP：<https://nlftp.mlit.go.jp/ksj/gml/data/N02/N02-25/N02-25_GML.zip>
- 基準日：2025-12-31。取得・最新版の確認：2026-10-20（日本時間）。
- 個別ページの使用許諾条件：CC BY 4.0（2020年以降のN02）。
- ライセンス：<https://creativecommons.org/licenses/by/4.0/>
- 公式サイト一般利用規約：<https://nlftp.mlit.go.jp/ksj/other/agreement.html>

国土数値情報（鉄道データ）をもとに、個人用RailMonitor開発のために加工して作成しました。加工内容は、門司港〜博多の抽出、属性の明示対応、同一頂点グラフの生成、計算用代表経路の選択、別経路候補の保存、駅線形の中点と範囲の投影、測地距離計算、WGS84互換座標への変換、SQLiteと検証図面への変換です。加工物を国の作成・承認・保証したものとして扱わないでください。

元データとその加工データを共有する場合、元の出典表示・ライセンスへのリンク・加工した旨を保ってください。原データの利用を妨げる追加的な制限や技術的制限を課さないでください。元データのライセンスを新規Pythonコードや第三者資料のライセンスに混同しないでください。

## JR九州の照合資料

- 路線と駅順：<https://www.jrkyushu-timetable.jp/sp/railway_list.html>
- 門司港から博多方面が下りであること：<https://www.jrkyushu-timetable.jp/cgi-bin/sp/sp-tt_list.cgi/28345>
- 営業キロ：JR九州「線区別ご利用状況」2024年度末、1ページ目：<https://www.jrkyushu.co.jp/company/info/data/pdf/2024senku.pdf>

駅順・方面・営業キロという照合に必要な事実だけを設定とレポートに記録しています。JRのPDF・サイト全体・時刻表・商用列車データはこのパッケージに再配布していません。JR資料のライセンスをCC BY 4.0とは表示していません。

## ソフトウェア

依存パッケージの版は `requirements.lock.txt`、実際のPython/SQLite/PROJ等の版は `output/metadata.json` に記録しています。仮想環境や第三者バイナリは配布ZIPに含めません。再導入時には各プロジェクトのライセンスが適用されます。新規ソースと前工程のSQLはこの個人プロジェクトの成果物として同梱しています。
