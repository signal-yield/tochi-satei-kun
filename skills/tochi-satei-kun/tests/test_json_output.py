# Copyright 2026 Koichi Matsuda / SignalYield Advisory
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Udemy Gate 0: 決定的JSON出力（--json-out）の検証。

査定計算そのものはテストで再実装せず、既存パイプライン関数をそのまま呼び出して
ctx を再構成し、JSON 出力と突き合わせる（test_pipeline.py の Layer 1 と同じ方式）。
"""
import json
import math
from datetime import date
from pathlib import Path

import sys

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from load_mlit import load_mlit_csv, load_koji_csv, load_kijun_csv
from scope import scope_dataframe, filter_recent_for_comparison, DEFAULT_COMPARISON_MONTHS
from similarity import compute_similarity, top_k
from time_adjust import annual_rate_for_city, apply_time_adjustment
from hedonic import fit_hedonic, annotate_district_mean, annotate_station_mean
from correction import apply_correction, compute_target_district_mean, compute_target_station_mean
from aggregation import assess
from main import run_pipeline
from json_writer import build_result, to_json_safe, write_json

SAMPLES = ROOT / "samples"
ASOF = date(2026, 5, 1)

REQUIRED_TOP_KEYS = {
    "schema_version", "engine", "valuation_status", "subject", "valuation_date",
    "scope", "time_adjustment", "hedonic", "comparables", "assessment", "warnings",
}


def _reference_assessment():
    """main.run_pipeline と同じ手順を独立に再現し、比較用の assess() 結果を得る。
    査定式そのものは assess() を直接呼ぶだけで、テスト側で再計算しない。
    """
    with open(SAMPLES / "sample_property.json", encoding="utf-8") as f:
        target = json.load(f)
    df = load_mlit_csv(SAMPLES / "sample_mlit.csv")
    koji = load_koji_csv(SAMPLES / "sample_koji.csv")
    scoped, _ = scope_dataframe(df, target, ASOF)
    rate_info = annual_rate_for_city(koji, None, target["市区町村名"],
                                     target_district=target.get("地区名"), asof=ASOF)
    adjusted = apply_time_adjustment(scoped, ASOF, rate_info["rate"])
    adjusted = annotate_district_mean(adjusted)
    adjusted = annotate_station_mean(adjusted)
    target["_target_district_mean"] = compute_target_district_mean(adjusted, target)
    target["_target_station_mean"] = compute_target_station_mean(adjusted, target)
    hed = fit_hedonic(adjusted)
    recent = filter_recent_for_comparison(adjusted, ASOF, months=DEFAULT_COMPARISON_MONTHS)
    if len(recent) < 3:
        recent = adjusted
    sim = compute_similarity(recent, target)
    top_cases = top_k(sim, k=3)
    corrected = apply_correction(top_cases, hed, target)
    return assess(corrected, target["面積(㎡)"])


def test_json_generated(tmp_path):
    """--json-out 相当の write_json 呼び出しで JSON ファイルが生成される。"""
    json_out = tmp_path / "result.json"
    out_path = run_pipeline(
        str(SAMPLES / "sample_property.json"),
        str(SAMPLES / "sample_mlit.csv"),
        str(SAMPLES / "sample_koji.csv"),
        out_dir=str(tmp_path),
        json_out_path=str(json_out),
    )
    assert out_path.exists()
    assert json_out.exists(), "JSONファイルが生成されていない"


def test_required_keys_present(tmp_path):
    json_out = tmp_path / "result.json"
    run_pipeline(
        str(SAMPLES / "sample_property.json"),
        str(SAMPLES / "sample_mlit.csv"),
        str(SAMPLES / "sample_koji.csv"),
        out_dir=str(tmp_path),
        json_out_path=str(json_out),
    )
    data = json.loads(json_out.read_text(encoding="utf-8"))
    missing = REQUIRED_TOP_KEYS - set(data.keys())
    assert not missing, f"必須キー欠落: {missing}"


def test_deterministic_output_bytes(tmp_path):
    """同一入力を2回実行し、生成JSONのバイト列が完全一致すること。"""
    out1 = tmp_path / "result_1.json"
    out2 = tmp_path / "result_2.json"
    run_pipeline(
        str(SAMPLES / "sample_property.json"),
        str(SAMPLES / "sample_mlit.csv"),
        str(SAMPLES / "sample_koji.csv"),
        out_dir=str(tmp_path / "out1"),
        json_out_path=str(out1),
    )
    run_pipeline(
        str(SAMPLES / "sample_property.json"),
        str(SAMPLES / "sample_mlit.csv"),
        str(SAMPLES / "sample_koji.csv"),
        out_dir=str(tmp_path / "out2"),
        json_out_path=str(out2),
    )
    assert out1.read_bytes() == out2.read_bytes(), "同一入力なのにJSONバイト列が一致しない"


def test_matches_excel_source_assessment(tmp_path):
    """JSON の assessment が、Excel生成に使われた assess() の結果と一致すること。
    丸めルール（円は整数、比率は小数第6位）を適用した上での比較。
    """
    json_out = tmp_path / "result.json"
    run_pipeline(
        str(SAMPLES / "sample_property.json"),
        str(SAMPLES / "sample_mlit.csv"),
        str(SAMPLES / "sample_koji.csv"),
        out_dir=str(tmp_path),
        json_out_path=str(json_out),
    )
    data = json.loads(json_out.read_text(encoding="utf-8"))
    ref = _reference_assessment()

    assert data["assessment"]["n_cases"] == ref["n_cases"]
    assert data["assessment"]["adopted_unit_price"] == round(ref["central_unit_price"])
    assert data["assessment"]["adopted_total_price"] == round(ref["central_total_price"])
    rng = ref["range"]
    pr = data["assessment"]["price_range"]
    assert pr["low_unit_price"] == round(rng["low_unit"])
    assert pr["central_unit_price"] == round(rng["central_unit"])
    assert pr["high_unit_price"] == round(rng["high_unit"])
    assert pr["low_total_price"] == round(rng["low_total"])
    assert pr["central_total_price"] == round(rng["central_total"])
    assert pr["high_total_price"] == round(rng["high_total"])


def test_json_generated_without_kijun_3_inputs(tmp_path):
    """PR #17 の3入力形式（基準地価なし）でも JSON が生成される。"""
    json_out = tmp_path / "result.json"
    run_pipeline(
        str(SAMPLES / "sample_property.json"),
        str(SAMPLES / "sample_mlit.csv"),
        str(SAMPLES / "sample_koji.csv"),
        out_dir=str(tmp_path),
        json_out_path=str(json_out),
    )
    assert json_out.exists()
    data = json.loads(json_out.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.0"


def test_json_generated_with_legacy_kijun_4_inputs(tmp_path):
    """旧4入力形式（基準地価あり）でも JSON が生成される。"""
    json_out = tmp_path / "result.json"
    run_pipeline(
        str(SAMPLES / "sample_property.json"),
        str(SAMPLES / "sample_mlit.csv"),
        str(SAMPLES / "sample_koji.csv"),
        str(SAMPLES / "sample_kijun.csv"),
        out_dir=str(tmp_path),
        json_out_path=str(json_out),
    )
    assert json_out.exists()
    data = json.loads(json_out.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.0"


def test_json_out_omitted_keeps_legacy_behavior(tmp_path):
    """--json-out 相当（json_out_path）を指定しない場合、従来どおりExcelのみ生成される。"""
    out_path = run_pipeline(
        str(SAMPLES / "sample_property.json"),
        str(SAMPLES / "sample_mlit.csv"),
        str(SAMPLES / "sample_koji.csv"),
        out_dir=str(tmp_path),
    )
    assert out_path.exists()
    assert out_path.suffix == ".xlsx"
    json_files = list(tmp_path.glob("*.json"))
    assert json_files == [], f"json_out_path 未指定なのにJSONが生成された: {json_files}"


def test_non_finite_values_are_sanitized():
    """NaN/Infinity が紛れ込んでも、出力JSONが規格外(NaN/Infinity)にならない。"""
    ctx = {
        "target": {"物件略号": "TEST"},
        "asof": ASOF,
        "scope_log": {"warnings": []},
        "rate_info": {"rate": float("nan"), "selected_points": []},
        "hedonic": {
            "ok": True, "n": 20, "r2": float("nan"), "adj_r2": float("inf"),
            "coefficients": {
                "const": {"beta": float("-inf"), "se": float("nan"), "p": 0.1, "label": "定数項"},
            },
            "skip_reason": None,
        },
        "cases": None,
        "assess": {
            "method": "test", "n_cases": 0, "warning": None,
            "central_unit_price": float("nan"), "central_total_price": float("nan"),
            "range": {"low_unit": float("nan"), "central_unit": float("nan"),
                      "high_unit": float("nan"), "low_total": float("nan"),
                      "central_total": float("nan"), "high_total": float("nan")},
        },
        "refs": {"hedonic_pred": float("nan")},
        "raw_case_count": 0,
    }
    result = build_result(ctx)
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False)
    assert "NaN" not in serialized
    assert "Infinity" not in serialized
    assert result["hedonic"]["adjusted_r2"] is None
    assert result["assessment"]["adopted_unit_price"] is None


def test_to_json_safe_converts_numpy_and_dates():
    import numpy as np
    import pandas as pd
    assert to_json_safe(np.int64(5)) == 5
    assert to_json_safe(np.float64(1.5)) == 1.5
    assert to_json_safe(np.float64("nan")) is None
    assert to_json_safe(date(2026, 5, 1)) == "2026-05-01"
    assert to_json_safe(pd.Timestamp("2026-05-01")) == "2026-05-01"
    assert to_json_safe({1, 2, 2}) == [1, 2]
