# データ出典・加工・ライセンス

出典：国土交通省「国土数値情報（鉄道データ）2025年度版」を加工して作成。

- [公式データカタログ](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N02-2025.html)
- [公式原本ZIP](https://nlftp.mlit.go.jp/ksj/gml/data/N02/N02-25/N02-25_GML.zip)
- 基準日：2025-12-31。2026-10-20に最新公開版が2025年度版であることを公式カタログで確認。
- [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) / [国土数値情報の利用規約](https://nlftp.mlit.go.jp/ksj/other/agreement.html)
- 原本ZIP SHA-256：`aaf76af133b2e771e538fabc4646d2e443dc1d5a67b221382a28d744e706cc9f`

取得した原本ZIPとHTTP取得情報・取得時ハッシュは `vendor/n02/data/raw/` に保存した。前工程の取得・変換コード、SQL、設定、駅ID原簿、個別品質警告は `vendor/n02/` に保存した。

今回の追加加工は、前工程のSQLiteからの読み取り、逆方向仮想エッジを双方向エッジへ整理する処理、終端の駅範囲を含む原点への距離の平行移動、近隣の他路線候補線形の取り込み、同一路線内の元頂点での分割・重複除去、推定用JSON/SQLiteへの変換である。元の線形を直線で補作していない。

表示・共有時は元の出典表示、ライセンスのリンク、加工した旨を保持する。加工物が国またはJR九州に承認・保証されたものと誤認される表示をしない。N02のCC BY 4.0を、本プロジェクトの新規ソースコードやJR九州の資料全体のライセンスと混同しない。

駅順と方向の事実は [JR九州の路線別駅一覧](https://www.jrkyushu-timetable.jp/sp/railway_list.html) などで照合した。営業キロ比較は [JR九州の線区別ご利用状況](https://www.jrkyushu.co.jp/company/info/data/pdf/2024senku.pdf) を参照した。JR公式サイト全体・PDF・列車別時刻表を再配布していない。原データのさらに詳しい加工履歴とライセンス情報は `vendor/n02/NOTICE.md`。
