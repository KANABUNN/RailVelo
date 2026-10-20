"""Quantify replay behavior. Synthetic metrics do not establish real GPS accuracy."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from railvelo.matcher import Matcher
from railvelo.network import Network


def jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def summary(values):
    return dict(n=len(values), mean=statistics.fmean(values) if values else None, median=statistics.median(values) if values else None, p95=percentile(values, .95), maximum=max(values) if values else None)


def result_measure(result, memberships, edge_lengths):
    membership = memberships.get((result.get("route_id"), result.get("edge_id")))
    if membership is None or result.get("offset_m") is None:
        return None
    offset = result["offset_m"]
    if membership["direction"] == -1:
        offset = edge_lengths[result["edge_id"]] - offset
    return membership["start_m"] + offset


def evaluate_scenario(fixture_root, entry, *, save_results=None):
    from generate_fixtures import distance
    network_path = fixture_root / entry["network"]
    document = json.loads(network_path.read_text(encoding="utf-8"))
    network = Network(document)
    matcher = Matcher(network)
    observations = jsonl(fixture_root / entry["observations"])
    truth = jsonl(fixture_root / entry["truth"])
    if len(observations) != len(truth):
        raise ValueError("Observation/truth length differs")
    memberships = {(e["route_id"], e["edge_id"]): e for e in document["route_edges"]}
    edge_lengths = {e["id"]: e["length_m"] for e in document["edges"]}
    results, elapsed = [], []
    for observation in observations:
        start = time.perf_counter()
        results.append(matcher.update(observation))
        elapsed.append((time.perf_counter() - start) * 1000)
    observed_errors, predicted_errors, point_errors = [], [], []
    eligible = route_confirmed = route_correct = direction_confirmed = direction_correct = 0
    statuses, event_types = {}, {}
    for i, (result, expected) in enumerate(zip(results, truth)):
        statuses[result["status"]] = statuses.get(result["status"], 0) + 1
        for event in result.get("events", []):
            event_types[event["type"]] = event_types.get(event["type"], 0) + 1
        measure = result_measure(result, memberships, edge_lengths)
        if result.get("route_id") == expected["route_id"] and measure is not None:
            error = abs(measure - expected["measure_m"])
            if result["status"] == "matched" and expected["sensor_valid"]:
                observed_errors.append(error)
            elif result["status"] == "predicted":
                predicted_errors.append(error)
        if expected["sensor_valid"] and result["status"] == "matched" and result.get("lat") is not None:
            point_errors.append(distance([result["lat"], result["lon"]], [expected["lat"], expected["lon"]]))
        # First three fixes are reported as startup and excluded from classification.
        if i < 3 or not expected["sensor_valid"]:
            continue
        eligible += 1
        if result["status"] == "matched" and result.get("route_id"):
            route_confirmed += 1
            route_correct += result["route_id"] == expected["route_id"]
        if result["status"] == "matched" and result.get("route_id") and result.get("direction") in (-1, 1):
            direction_confirmed += 1
            direction_correct += result["route_id"] == expected["route_id"] and result["direction"] == expected["direction"]
    metrics = dict(name=entry["name"], kind="synthetic", observations=len(observations), startup_fixes_excluded=3, valid_sensor_fixes_after_startup=eligible,
                   statuses=statuses, events=event_types,
                   route=dict(confirmed=route_confirmed, correct=route_correct, accuracy_when_confirmed=route_correct / route_confirmed if route_confirmed else None, coverage=route_confirmed / eligible if eligible else None),
                   direction=dict(confirmed=direction_confirmed, correct=direction_correct, accuracy_when_confirmed=direction_correct / direction_confirmed if direction_confirmed else None, coverage=direction_confirmed / eligible if eligible else None),
                   observed_along_track_error_m=summary(observed_errors), predicted_along_track_error_m=summary(predicted_errors), observed_horizontal_error_m=summary(point_errors),
                   processing_ms=summary(elapsed), total_processing_ms=sum(elapsed),
                   network_edges=len(document["edges"]), network_sha256=hashlib.sha256(network_path.read_bytes()).hexdigest(),
                   input_sha256=hashlib.sha256((fixture_root / entry["observations"]).read_bytes()).hexdigest())
    if save_results is not None:
        save_results.mkdir(parents=True, exist_ok=True)
        (save_results / f"{entry['name']}.results.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in results), encoding="utf-8")
    return metrics


def render_markdown(report):
    def percentage(value):
        return "判定なし" if value is None else f"{value * 100:.2f}%"

    def metres(value):
        return "—" if value is None else f"{value:.2f}"

    lines = ["# GPSマップマッチング評価（合成データ限定）", "",
             "実走行ログは入手できていない。以下は線路形状から生成した観測値と独立の真値を比較した結果であり、実測GPS精度を保証しない。",
             "N02の元データの位置誤差・実際の複線上下線・実測トンネル挙動も測定していない。", "",
             "各シナリオの最初の3観測を起動期間として路線・方向集計から除き、センサー有効な観測を分母とした。",
             "正解率は `matched` として確定した結果に限る条件付き正解率。確定率を併記し、未確定を正解に含めない。",
             "方向は路線が正解でかつ方向が一致する場合のみ正解。位置誤差は真の路線を確定できた観測について線路上の距離で評価した。",
             "実測を処理した位置と、測位喪失中の短期推定位置の誤差を分けて集計する。", "",
             "| シナリオ | 観測数 | 路線正解率 / 確定率 | 方向正解率 / 確定率 | 実測処理位置誤差 p95 (m) | 短期推定誤差 p95 (m) | 処理 p95 (ms) |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for scenario in report["scenarios"]:
        route, direction = scenario["route"], scenario["direction"]
        lines.append(f"| {scenario['name']} | {scenario['observations']} | {percentage(route['accuracy_when_confirmed'])} / {percentage(route['coverage'])} | {percentage(direction['accuracy_when_confirmed'])} / {percentage(direction['coverage'])} | {metres(scenario['observed_along_track_error_m']['p95'])} | {metres(scenario['predicted_along_track_error_m']['p95'])} | {scenario['processing_ms']['p95']:.3f} |")
    lines += ["", "`corridor_full` は実際のN02線形全区間に約500 m間隔・25秒間隔で生成した疎な走行。",
              "駅イベントの確認は2秒間隔の専用シナリオで実施する。25秒間隔の全区間走行は位置・路線・方向の評価に用いる。",
              "`branch_merge` の共用区間と `ambiguous_stationary` の等距離並走線は、確定できない結果が正しい挙動となる。",
              "`tunnel_reentry` は信号喪失と復帰直後の悪い観測を重ねた合成例。復帰後も候補の支持が十分になるまで確定を控えるため確定率が低い。",
              "この低い確定率を含め、実際のトンネル前後の再捕捉時間とパラメータは実走行で調整する必要がある。", "",
              "駅停止・発車、通過、駅間長時間停車・再開、駅周辺外縁停止の到着抑制、測位喪失を跨ぐ通過イベントの抑制は自動テストで確認する。",
              "短期推定は `predicted`、確定を止めた状態は `lost` / `uncertain` として区別する。予測から駅イベントを生成しない。", "",
              "| シナリオ | matched | predicted | uncertain | lost | rejected |",
              "|---|---:|---:|---:|---:|---:|"]
    for scenario in report["scenarios"]:
        counts = scenario["statuses"]
        lines.append("| " + scenario["name"] + " | " + " | ".join(str(counts.get(status, 0)) for status in ("matched", "predicted", "uncertain", "lost", "rejected")) + " |")
    lines += ["", "上の状態件数は起動期間・無効センサーを含む全観測を対象とする。低精度や異常値を除外した後の確定率だけで継続性を評価しないために併記した。", "",
              "評価環境: " + report["environment"]["platform"] + " / " + report["environment"]["processor"],
              "Python: " + report["environment"]["python"].replace("\n", " "),
              "処理時間はこのWindows環境のPython推論部分のwall-clock値。iPhone・Swiftの性能測定値ではない。", "",
              "再現手順:", "", "```powershell", "python scripts/generate_fixtures.py", "python -m unittest discover -s tests -v", "python scripts/evaluate.py --save-results fixtures/results", "```", "",
              "機械可読の詳細・件数・入力ハッシュ・環境は `evaluation.json`。Swiftとの比較は、同じ観測とネットワークを両実装で処理し、",
              "`scripts/compare_replays.py` へ両結果を渡して実行する。Python出力同士の比較や比較プログラムの単体テストはSwift検証の代わりにはならない。",
              "本Windows環境ではSwift/Xcodeが利用できず、Swiftビルド・Swift/Python比較・iOSシミュレーター・実機検証は未実行。macOS CIの検証手順を用意したが、その成功はこの結果に含めていない。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=ROOT / "fixtures")
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "evaluation.json")
    parser.add_argument("--scenario", action="append", help="Evaluate only this scenario (repeatable)")
    parser.add_argument("--save-results", type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.fixtures / "manifest.json").read_text(encoding="utf-8"))
    entries = [entry for entry in manifest["scenarios"] if not args.scenario or entry["name"] in args.scenario]
    if args.scenario and set(args.scenario) - {e["name"] for e in entries}:
        parser.error("Unknown scenario requested")
    report = dict(schema_version=1, evaluation_kind="synthetic_only", real_gps_logs_evaluated=False,
                  inference_source_sha256={name: hashlib.sha256((ROOT / "python" / "railvelo" / name).read_bytes()).hexdigest() for name in ("network.py", "matcher.py", "events.py")},
                  limitations=["Ground truth follows source geometry; source positional error is not measured.", "No real train logs, tunnel propagation or iPhone GPS behavior were measured.", "Classification accuracy is conditional on a confirmed result; coverage is reported separately.", "Observed and short-gap predicted position errors are reported separately.", "Route can be unknowable on shared tracks; synthetic route labels express generator intent.", "Wall-clock timing includes Python inference only on this machine and is not an iOS benchmark."],
                  environment=dict(python=sys.version, platform=platform.platform(), machine=platform.machine(), processor=platform.processor()), scenarios=[])
    for entry in entries:
        metrics = evaluate_scenario(args.fixtures, entry, save_results=args.save_results)
        report["scenarios"].append(metrics)
        print(f"{entry['name']}: n={metrics['observations']} route={metrics['route']['accuracy_when_confirmed']} coverage={metrics['route']['coverage']} p95={metrics['processing_ms']['p95']:.3f}ms")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    print(f"Report: {args.output}")


if __name__ == "__main__":
    main()
