# 実走CSVの解析と正解記録の照合

更新日: 2026-10-21。対象は端末から共有したRailVeloのCSV。解析プログラムはPython標準ライブラリと既存のNetwork読込だけを使用し、元ファイルや線路DBを変更せず、外部へ送信しない。

この手順と自動テストは実走性能の合格を示さない。自動テストは人工のCSVによる計算・分母・不明値・ファイル処理の検証である。実走ファイルがない指標は未評価、CPU等の測定がない指標は未測定として残す。

## 非公開の作業場所

実GPS、手動記録、測定、解析JSON/Markdownはリポジトリ直下の`recordings/`以下へ保存する。このディレクトリはGitの除外対象。GitHub issue、公開CI成果物、公開レポートへ実走CSVや位置を含む画像を添付しない。解析結果にも路線・駅・セッションIDが含まれ得るため、集計結果も個人記録として扱う。

```powershell
New-Item -ItemType Directory -Force recordings\trial-001
Copy-Item docs\templates\ride_truth.csv recordings\trial-001\truth.csv
Copy-Item docs\templates\device_measurements.csv recordings\trial-001\measurements.csv
Copy-Item docs\templates\manual_observation_log.md recordings\trial-001\notes.md
```

iPhoneから共有したCSVを同じフォルダーへ`ride.csv`として保存する。元CSVを編集せず、手入力の訂正は別の正解記録・メモで行う。必要なバックアップは本人の非公開の保管先へ作る。プログラムはGit操作・自動公開・クラウドへのアップロードを行わない。

## 最初の解析

正解記録を用意する前でも、観測件数、有効速度、除外理由、推定状態、イベント件数、観測間隔、線形への残差を確認できる。

```powershell
python scripts/analyze_ride.py recordings/trial-001/ride.csv --network data/railway.sqlite --output recordings/trial-001/analysis.json --markdown recordings/trial-001/analysis.md
```

正解記録を付けた後は同じ元CSVへ照合する。

```powershell
python scripts/analyze_ride.py recordings/trial-001/ride.csv --network data/railway.sqlite --truth recordings/trial-001/truth.csv --measurements recordings/trial-001/measurements.csv --output recordings/trial-001/analysis.json --markdown recordings/trial-001/analysis.md
```

測定ファイルを作っていない場合、`--measurements`を省略する。空欄を0で埋めない。JSONには入力のSHA-256を記録するため、後から同じファイルの解析かを照合できる。1ファイル内に複数のセッションや実GPS/リプレイを混在させた入力は拒否する。出力先で元CSV・正解・測定・線路DBを上書きする操作も拒否する。

対応入力は従来の36列CSVと、末尾に診断列を追加したCSV。診断行やセッション要約がない旧CSVでも通常の解析は行える。旧CSVだけから正確な保存遅延や中断時の実時間上の終了時刻を補作しない。

## 駅ID・方向・距離の参照

次で線路DBの公開情報から路線・駅IDの対応表を作れる。実走GPSは入力しない。

```powershell
python scripts/analyze_ride.py --network data/railway.sqlite --catalog-output recordings/reference-catalog.csv
```

初期対象路線のIDは`jrkyushu.kagoshima.mojiko-hakata`。方向は代表経路の順方向が`1`、逆方向が`-1`。名称・駅ID・順序・方向ラベルは対応表を正とする。次駅の正解は地理的に次に通る駅であり、列車の次の停車駅ではない。

`map_anchor_along_track_m`はN02の駅線形を投影した代表位置。同じ地図から作った基準値なので、これとの一致を独立した現地測量精度とは呼ばない。目視で駅名・方面を確認できても、正確な線路距離が分からなければ`along_track_m`は空欄にする。営業キロや駅名標の位置を、そのままアプリの代表線形の累計距離へ流用しない。

## 正解記録の書式

空の雛形は`docs/templates/ride_truth.csv`。時刻は`2026-10-21T12:34:56+09:00`または`2026-10-21T03:34:56Z`のようにタイムゾーンを付ける。これは書式例であり試験結果ではない。時刻のタイムゾーンがない記録は拒否する。アプリ表示を見て同じ値を正解欄へ転記せず、車内表示・現地観察・別の記録など、根拠を`reference_basis`と非公開メモに残す。

| 列 | 入れる内容 |
| --- | --- |
| `reference_id` | 重複しない手動記録ID |
| `kind` | `position`、`event`、`event_window`、`outage` |
| `time_utc` | 照合する時刻。`+09:00`等の時差表記も可 |
| `end_time_utc` | `event_window`と`outage`の終了時刻 |
| `route_id` / `direction` | 分かる路線IDと方向。方向が分かる場合は路線IDも必要 |
| `station_id` / `event_type` | イベントの駅と種類 |
| `along_track_m` | 独立した根拠がある代表経路上の距離。路線IDも必要 |
| `previous_station_id` / `next_station_id` | その時刻に実際にいる駅間。分からない列は空欄 |
| `tolerance_s` | 記録時刻の許容差。空欄は5秒 |
| `reference_basis` / `notes` | 正解とした根拠・不確実性。自由メモは解析出力へ転載しない |

`position`は指定時刻に最も近い観測を許容差以内で1件選ぶ。観測がない区間へ補間しない。同距離の時刻では前の観測を選ぶ。路線しか分からない記録は方向・駅・距離の分母へ含めない。方向の`0`は正解値として使わず、分からなければ空欄にする。

`event`は到着`arrival`、発車`departure`、通過`pass`、駅間停止`between_station_stop`、再走行`resume`。到着・発車の現地観察は列車が止まった/動き出した時刻を基準にし、扉の開閉時刻と区別する。駅中心の通過を車内から厳密に特定できない場合は、その不確実性に合わせた許容差を記録する。イベントは種類・分かっている駅/路線/方向・時刻差で一対一照合する。同じ予測を複数の正解へ使わず、時系列順の照合数を最大化し、その範囲で時間差を最小化する。

`event_window`は、その時間内の対象イベントを漏れなく手動記録した範囲を宣言する。駅/路線/イベント種類を指定した場合はその対象だけが完全記録の範囲となる。単に一部の駅をメモしただけの区間では設定しない。この宣言がなければ、手動メモがない予測を誤検出とは扱わず、適合率は未評価にする。範囲を宣言すると、その範囲内で照合できなかった予測が誤検出の分母になる。

`outage`は、測位が途切れ始めた時刻から、独立した観察で受信環境が戻った時刻まで。終了時刻以降に正しい路線の`matched`へ初めて戻るまでを復帰時間として計測する。正解の路線が分からない記録は復帰の正否を採点しない。既定の探索上限は120秒。そこまで記録が残っていなければ打切りとして分け、復帰失敗には数えない。上限まで記録があり正しい確定がなければタイムアウトとなる。`--max-recovery-s`で変更できる。

## 分母と不明の扱い

| 指標 | 分母・除外 |
| --- | --- |
| 路線/方向/前駅/次駅 | その値が記入された`position`参照のみ。許容差内の観測なし・未確定・項目欠損は`unknown` |
| 確定時正解率 | 正解 / (正解 + 誤り)。不明を除くためcoverageと併記 |
| 対象全体の正解割合 | 正解 / 対象の正解記録数。不明を成功扱いしない |
| coverage | 確定比較できた参照数 / 対象の正解記録数 |
| 線路距離誤差 | 距離の参照があり、同じ路線で、edge/offsetと線路DBから累計距離を求められた観測のみ。予測は別集計 |
| イベント再現率 | 許容差内で一対一照合できた手動イベント / 手動イベント数 |
| イベント適合率 | 完全記録を宣言した範囲内の照合済み予測 / 同範囲内の全予測。未宣言ならnull |
| 復帰割合 | 復帰成功 / (復帰成功 + 全探索時間を観測できたタイムアウト)。参照不足・打切りは別計数 |

距離は絶対誤差に加え、進行方向ではなく代表経路の累計距離の正負による偏りを出す。p95はnearest-rank方式。統計には件数`n`を付け、対象がなければ平均や正解率は`null`。イベントの推定発生時刻と正解時刻の差、イベントが観測結果へ現れるまでのアルゴリズム上の遅れを分け、CPU処理時間と呼ばない。

線路への残差`raw_to_matched_edge_residual_m`は、GPS生座標から確定したedgeの形状への最短距離。`raw_to_exported_snapped_point_m`は生座標から出力されたスナップ座標への距離。どちらも地図や正解が独立していないため、GPS測位誤差や実走精度の正解値ではない。

観測間隔が閾値を超えた件数には、粗いサンプリング、一時停止、OS停止も含まれ得る。`long_observation_intervals`をそのままトンネル欠測やGPS障害回数と呼ばない。明示的な欠測行・状態遷移・手動メモと照合する。不正/逆行/未来時刻として除外された行は、この時間軸と参照位置の照合からも除外する。

## 端末性能・電池の別記録

雛形は`docs/templates/device_measurements.csv`。本人が実際に確認した値だけ記入し、測り方と対象build/端末/条件を非公開メモへ残す。解析プログラム自身がiPhoneのCPUやメモリを測ったとは表現しない。

| 列 | 単位・意味 |
| --- | --- |
| `session_id` | 対象CSVのセッション。空欄も可だが、別IDがあれば拒否 |
| `time_utc` | タイムゾーン付き測定時刻 |
| `cpu_percent_one_core` | 1コア100%基準。複数コア使用時に100超も可。別基準の値を無断換算しない |
| `resident_memory_mb` | 測定ツールのresident memory、MB単位。実際の単位・定義をmethodへ記入 |
| `battery_percent` | 実測残量0〜100 |
| `charging` | `true` / `false` / `unknown`。不明を非充電として扱わない |
| `method` / `notes` | 使用した測定方法・端末条件。自由メモは出力へ転載しない |

CPU/メモリ/電池の未記入項目は`null`。電池の時間当たり減少は2件以上の時刻付き残量があり、その間の充電状態がすべて`false`のときだけ算出する。充電/不明や残量増加を含むときは未評価と理由を返す。残量表示の丸めや温度の影響を除いた消費電力の測定ではない。

39列版に受信時刻と永続化処理開始時刻があれば、`received_to_persistence_start_s`を集計する。これは受信からキュー待機・推定等を経て保存処理へ入るまでの経過で、SQL実行・commit時間を含まない。CPU時間・単独のキュー待機・SQLite所要時間は分離計測がなければ`null`のまま。リプレイの元GPS時計と壁時計は異なるため、リプレイでは元観測→受信の差を遅延として計算しない。

## 診断の限界と次の試験

旧36列には受信・保存処理開始時刻やOSエラー詳細がなく、画面の遅延とGPSの遅延を厳密に分離できない。拡張CSVの`diagnostic`行はkind/domain/codeの件数を集計し、個人情報を含み得るdetail本文は集計出力へ転載しない。`session_summary`があれば開始/終了時刻から実時間のセッション長を算出するが、最後に保存処理へ渡した時刻をディスクcommit完了時刻とは扱わない。実際のOS終了直前に受信した未commit入力は失われる可能性がある。

最初は短区間を前面記録し、CSV再読込と駅名・方面の照合を確認してから、背景・画面ロック・全区間・長時間へ進める。各試験の操作と未検証条件は[実機試験計画](DEVICE_TEST_PLAN.md)へ引き継ぐ。プログラムの人工入力テストは次で実行する。

```powershell
python -m unittest discover -s tests -p test_ride_analysis.py -v
```
