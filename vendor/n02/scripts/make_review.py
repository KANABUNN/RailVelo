"""Create a self-contained, offline geographic review page and Markdown report."""
import argparse
import html
import json
from pathlib import Path
import sqlite3
from pyproj import Transformer

T=Transformer.from_crs(6668,6670,always_xy=True)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory",type=Path)
    args=p.parse_args()
    out=args.directory.resolve()
    meta=read(out/"metadata.json")
    qa=read(out/"validation.json")
    issues=read(out/"quality_issues.json")
    lines=read(out/"corridor.geojson")["features"]
    stations=read(out/"station_lines.geojson")["features"]
    excluded=read(out/"nearby_excluded.geojson")["features"]
    db=sqlite3.connect(out/"rail_jrkyushu.sqlite")
    db.row_factory=sqlite3.Row
    primary=[dict(r) for r in db.execute("SELECT s.*,p.chainage_m,p.sequence FROM stations s JOIN rm_station_positions p ON s.id=p.station_id ORDER BY p.sequence")]
    candidates=[dict(r) for r in db.execute("SELECT e.id,e.length_m,m.source_ids_json FROM rail_edges e JOIN rm_edge_metadata m ON e.id=m.edge_id WHERE m.role='candidate' AND e.id LIKE '%.f'")]
    db.close()
    all_coords=[c for f in lines for c in f["geometry"]["coordinates"]]
    transformed=[T.transform(*c) for c in all_coords]

    def pane(title, center=None, halfwidth=None, halfheight=None, overview=False):
        if center:
            cx,cy=T.transform(*center)
            bounds=(cx-halfwidth,cy-halfheight,cx+halfwidth,cy+halfheight)
        else:
            bounds=(min(x for x,y in transformed)-1000,min(y for x,y in transformed)-1000,
                    max(x for x,y in transformed)+1000,max(y for x,y in transformed)+1000)
        xmin,ymin,xmax,ymax=bounds
        w,h=850,490
        scale=min((w-50)/(xmax-xmin),(h-50)/(ymax-ymin))
        ox=(w-scale*(xmax-xmin))/2
        oy=(h-scale*(ymax-ymin))/2

        def xy(c):
            x,y=T.transform(*c)
            return ox+(x-xmin)*scale,h-oy-(y-ymin)*scale

        def line_svg(f,color,width,dash=""):
            g=f["geometry"]
            ps=[g["coordinates"]] if g["type"]=="LineString" else g["coordinates"]
            paths=[]
            for cs in ps:
                coordinates=" ".join(f"{x:.2f},{y:.2f}" for x,y in map(xy,cs))
                text=html.escape(json.dumps(f["properties"],ensure_ascii=False))
                paths.append(f'<polyline points="{coordinates}" fill="none" stroke="{color}" stroke-width="{width}" stroke-dasharray="{dash}"><title>{text}</title></polyline>')
            return "".join(paths)
        body=[]
        for f in excluded:
            body.append(line_svg(f,"#cf7918",1.8))
        for f in lines:
            body.append(line_svg(f,"#135da3" if f["properties"]["role"]=="reference" else "#bd37af",3 if overview else 3.5,"" if f["properties"]["role"]=="reference" else "6 3"))
        for f in stations:
            body.append(line_svg(f,"#14946b",5.5))
        for row in primary:
            x,y=xy((row["longitude"],row["latitude"]))
            if 0<=x<=w and 0<=y<=h:
                body.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3.5" fill="white" stroke="#113b59" stroke-width="1.5"/>')
                if not overview or row["public_name"] in ("門司港","小倉","折尾","赤間","福間","香椎","博多"):
                    label=html.escape(row["public_name"])
                    body.append(f'<text x="{x+8:.2f}" y="{y-7:.2f}" font-size="15" paint-order="stroke" stroke="white" stroke-width="4" fill="#142b40">{label}</text>')
        bar_m=10000 if overview else 500 if halfwidth and halfwidth>2000 else 100
        bar=bar_m*scale
        body.append(f'<path d="M30 {h-25}h{bar:.1f}" stroke="#20384b" stroke-width="4"/><text x="30" y="{h-35}" font-size="14">{bar_m:g} m / N↑</text>')
        return f'<section><h2>{html.escape(title)}</h2><svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" aria-label="{html.escape(title)}"><rect width="{w}" height="{h}" fill="#f5f8fb"/>{"".join(body)}</svg></section>'

    panes=[pane("全区間：計算用代表経路",overview=True),
           pane("門司・小倉：近接する他路線と線形",(130.913,33.909),6000,3500),
           pane("黒崎・陣原・折尾：複数線形を保存",(130.743,33.867),5500,1900),
           pane("折尾：同一駅コードの異なる位置",(130.713,33.864),850,490),
           pane("海老津付近：別経路候補",(130.607,33.823),2400,1500),
           pane("博多：端点・分岐候補・他社路線",(130.421,33.594),1600,1800)]
    rows="".join(f'<tr><td>{r["sequence"]+1}</td><td>{html.escape(r["public_name"])}</td><td>{r["chainage_m"]/1000:.3f}</td></tr>' for r in primary)
    issue_rows="".join(f'<tr><td>{r["id"]}</td><td>{html.escape(r["code"])}</td><td>{html.escape(json.dumps(r["details"],ensure_ascii=False))}</td></tr>' for r in issues)
    comparisons=meta.get("official_operating_km_comparison",[])
    comparison_rows="".join(f'<tr><td>{html.escape(r.get("from",r.get("from_station","")))}</td><td>{html.escape(r.get("to",r.get("to_station","")))}</td><td>{r["operating_km"]:.1f}</td><td>{r["n02_reference_m"]/1000:.3f}</td><td>{r["difference_m"]:.3f}</td></tr>' for r in comparisons)
    page=f'''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>N02 門司港〜博多 品質レビュー</title>
<style>body{{font:16px system-ui,'Yu Gothic',sans-serif;color:#18354c;margin:0;background:#e9eff4}}main{{max-width:1500px;margin:auto;padding:28px}}h1{{margin:0 0 12px}}.note{{background:#fff4d7;border-left:5px solid #df9f28;padding:16px;line-height:1.8}}.metrics{{display:flex;gap:14px;margin:20px 0;flex-wrap:wrap}}.metrics span,section{{background:white;border-radius:12px;padding:18px}}.maps{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}}h2{{font-size:18px;margin:0 0 12px}}svg{{width:100%;display:block;overflow:hidden}}table{{border-collapse:collapse;width:100%;background:white;font-size:14px}}td,th{{border:1px solid #d6e0e6;padding:8px;text-align:left;overflow-wrap:anywhere}}.sources{{line-height:1.7;margin:22px 0}}@media(max-width:850px){{.maps{{grid-template-columns:1fr}}main{{padding:14px}}}} </style>
<main><h1>N02 門司港〜博多 データ品質レビュー</h1><div class="note">これはN02に基づく計算用データです。代表経路は最短経路として算出しています。上下線・番線・転轍器・各分岐の通行可否は未確認です。駅の緑色の範囲はN02駅線形であり、実測したホーム長ではありません。</div>
<div class="metrics"><span><b>32駅 / 35駅線形</b></span><span><b>{meta['reference_center_length_m']/1000:.3f} km</b> 駅中心間の形状弧長</span><span><b>{qa['passed']}/{qa['total']}</b> 自動検証</span><span><b>{qa['counts']['directed_edges']}</b> 双方向の計算用辺</span></div>
<p>青：代表経路　紫破線：他の経路候補　緑：N02駅線形　橙：対象から除外した周辺の別路線・別事業者<br>図形にカーソルを置くと元属性を表示。背景地図は使用していません。距離目盛りは平面直角座標系II（EPSG:6670）です。</p>
<div class="maps">{''.join(panes)}</div><div class="sources">出典：<a href="https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N02-2025.html">国土交通省 国土数値情報 鉄道2025年度版</a>（2025-12-31基準、CC BY 4.0）を加工して作成。抽出・グラフ化・代表経路選択・駅投影・距離計算を実施。国が作成した成果物ではありません。地理座標はJGD2011。<a href="https://creativecommons.org/licenses/by/4.0/">ライセンス</a></div>
<h2>営業キロとの比較</h2><p>JR九州の2024年度末資料と比較。形状弧長との差の原因は未確定です。距離を引き伸ばす補正はしていません。</p><table><tr><th>始駅</th><th>終駅</th><th>営業キロ km</th><th>N02形状 km</th><th>差 m</th></tr>{comparison_rows}</table>
<h2>駅順と中心位置</h2><table><tr><th>#</th><th>駅</th><th>門司港の駅線形中心からの形状距離 km</th></tr>{rows}</table>
<h2>未確認事項・要検証箇所</h2><table><tr><th>ID</th><th>分類</th><th>詳細</th></tr>{issue_rows}</table></main></html>'''
    (out/"review.html").write_text(page,encoding="utf-8")
    md=["# N02 門司港〜博多 品質検証結果", "",f"判定：**{qa['status']}**。自動検証 {qa['passed']}/{qa['total']} 件。物理的な分岐の接続可否・実走受入は未確認です。", "",
        f"32駅、元の駅線形35件、ノード{qa['counts']['nodes']}件、計算用の有向辺{qa['counts']['directed_edges']}件、代表経路{qa['counts']['reference_edges']}辺。",
        f"門司港中心〜博多中心のGRS80弧長：{meta['reference_center_length_m']:.3f} m。全端駅範囲を含む代表経路：{meta['full_reference_length_m']:.3f} m。", "",
        "## 検証結果", "", "| 検証 | 結果 |", "|---|---|"]
    md += [f"| {c['name']} | {'PASS' if c['passed'] else 'FAIL'} |" for c in qa['checks']]
    md += ["", "## 営業キロとの独立比較", "", "[JR九州 2024年度末 線区別ご利用状況](https://www.jrkyushu.co.jp/company/info/data/pdf/2024senku.pdf) 1ページ目の2区間を照合。合計は両区間の和です。差の原因は未確定で、較正は行っていません。", "", "| 始駅 | 終駅 | 営業キロ km | N02形状 m | 差 m | 差 % |", "|---|---|---:|---:|---:|---:|"]
    md += [f"| {r.get('from',r.get('from_station'))} | {r.get('to',r.get('to_station'))} | {r['operating_km']:.1f} | {r['n02_reference_m']:.3f} | {r['difference_m']:.3f} | {r['difference_percent']:.3f} |" for r in comparisons]
    md += ["", "## N02の限界と処理結果", "",
           "- 元属性は `N02_003=鹿児島線`、`N02_004=九州旅客鉄道`、`N02_001=11`、`N02_002=2`。運行上の呼び名「鹿児島本線」への対応は明示設定。直通する列車の系統・列車ID・停車駅はこの属性からは決まらない。",
           "- 駅順32駅はJR九州公式の路線別駅一覧に照合。門司港→小倉→博多を下りとする方向は公式駅案内で確認。GPSから進行方向を推定する処理は今回の対象外。",
           "- 門司・陣原・折尾は同じ駅コードでも駅線形が複数ある。35件すべての元属性・元形状を保存し、32駅のアプリIDとは別に管理する。折尾の異なる線形の用途や現行ホームとの対応を推測しない。",
           "- 原線形の同一頂点だけを接続。スナップ、直線の補間による穴埋め、平面上の交点からの接続は0件。入力の接続性は地図表現上のもので、転轍器・進入方向・列車の通行可否の証明にはならない。",
           "- 代表経路は距離計算のために最短経路を明示的に選択したもの。別経路候補もDBに残し `direction=unknown` とする。上下方向の仮想辺は実在する上下線を意味しない。",
           "- 採用した線形にnull/空/不正幾何はない。全駅代表点に元線形上の経路を確保。これは現実の線路形状が欠けていないという評価ではない。N02で表現されない渡り線・ホーム別線路・細かなカーブの欠落は判定不能。",
           "- 周辺150mの別事業者・別路線68地物は別ファイルで保存し、DBの経路には取り込まない。JR貨物名義の地物が見つからなくても、貨物の走行・共用線が存在しない証拠にはならない。N02の対象は旅客鉄道・軌道。",
           "- `platform_begin_m/end_m` はN02駅線形に基づく範囲。実ホーム端・停止位置・扉開時刻との一致は未確認。端駅の範囲を欠かさないよう代表経路は駅中心より外側まで保持する。",
           "- 距離は平面の緯度経度差や駅間直線距離ではなく、GRS80楕円体上の各線分長の和。営業キロへ較正していない。駅中心もN02駅線形の長さ中点という便宜的な定義。",
           "- JGD2011→WGS84はPROJの静的変換（公称精度1m、今回のパイプラインはno-op）。地殻変動・観測元期・GNSSの時刻依存変換は扱っていない。線路番号レベルの測位精度を主張しない。", "",
           "## 別経路候補（実際の通行可否は未確認）", "", "| 辺（逆向きも保存） | 弧長 m | 元地物 |", "|---|---:|---|"]
    md += [f"| {r['id']} | {r['length_m']:.3f} | {r['source_ids_json']} |" for r in candidates]
    md += ["", "## 個別の要確認事項", ""]
    for r in issues:
        md += [f"### {r['id']} {r['code']}", "", "関連地物："+", ".join(r["related_ids"]), "", "```json",json.dumps(r["details"],ensure_ascii=False,indent=2),"```",""]
    md += ["## 今回完了した範囲", "", "取得・抽出・計算用グラフ・双方向の辺・駅範囲・距離・SQLite・自動検証・オフライン図面生成をWindows上で実行。元のSQLの定義を変更せず、出典と品質管理の表を追加。", "",
           "## 未完・受入が必要な範囲", "", "実際の分岐・番線対応の現地／一次図面照合、各隣接駅間の営業キロとの全数照合、距離差の原因特定、乗車GPSによるマップマッチング、到着・通過判定、iOSビルド・実機試験。自動検証PASSをこれらの完了と解釈しない。", "",
           "## 出典・利用条件", "", "[国土交通省 N02 鉄道2025年度版](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N02-2025.html)、基準日2025-12-31、CC BY 4.0。出典、版、加工内容、ライセンスを同梱DBとNOTICEに表示。", "",
           "[JR九州 路線別駅一覧](https://www.jrkyushu-timetable.jp/sp/railway_list.html)、[門司港 方面案内](https://www.jrkyushu-timetable.jp/cgi-bin/sp/sp-tt_list.cgi/28345)で駅順と下り方向を確認。時刻表の時刻・列車データは取得・保存していない。", ""]
    (out/"QUALITY_REPORT.md").write_text("\n".join(md),encoding="utf-8")
    print(f"Created review.html and QUALITY_REPORT.md in {out.name}")


if __name__=="__main__":
    main()
