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

"""Udemy Gate 0 向け決定的 JSON 出力。

xlsx_writer.py に渡している ctx（target / scope_log / rate_info / hedonic /
cases / assess 等）を正本として、そのまま JSON へ写し取る。ここでは一切の
査定計算を行わない（値は既存パイプラインの結果をそのまま整形するのみ）。

丸めルール（表示上のみ。査定計算そのものは変更しない）：
- 円建ての金額（単価・総額）: 整数円に丸め（Python の round、偶数丸め）
- 変動率・類似度・R²・回帰係数等の比率: 小数第6位に丸め
"""
import json
import math
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from scope import DEFAULT_COMPARISON_MONTHS
from version import ENGINE_VERSION

SCHEMA_VERSION = "1.0"
ENGINE_NAME = "tochi-satei-kun"

MONEY_NDIGITS = 0
RATE_NDIGITS = 6

_SUBJECT_FIELD_MAP = [
    ("物件略号", "label"),
    ("市区町村名", "city"),
    ("地区名", "district"),
    ("面積(㎡)", "area_sqm"),
    ("最寄駅:名称", "nearest_station"),
    ("最寄駅:距離(分)", "station_walk_min"),
    ("前面道路:種類", "road_type"),
    ("前面道路:幅員(m)", "road_width_m"),
    ("前面道路:方位", "road_direction"),
    ("土地の形状", "shape"),
    ("都市計画", "zoning"),
    ("建ぺい率(%)", "building_coverage_ratio_pct"),
    ("容積率(%)", "floor_area_ratio_pct"),
]


def to_json_safe(value):
    """numpy/pandas/date 型を標準 JSON 型へ再帰的に変換。NaN/Inf は None にする。"""
    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        f = float(value)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (set, frozenset)):
        return sorted(to_json_safe(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [to_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): to_json_safe(v) for k, v in value.items()}
    if isinstance(value, pd.Series):
        return to_json_safe(value.tolist())
    if isinstance(value, np.ndarray):
        return to_json_safe(value.tolist())
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _round_money(value):
    v = to_json_safe(value)
    if v is None:
        return None
    return int(round(float(v), MONEY_NDIGITS))


def _round_rate(value):
    v = to_json_safe(value)
    if v is None:
        return None
    return round(float(v), RATE_NDIGITS)


def _build_engine() -> dict:
    return {"name": ENGINE_NAME, "version": ENGINE_VERSION}


def _build_valuation_status() -> dict:
    return {
        "purpose": "媒介査定・一次スクリーニング参考",
        "is_formal_appraisal": False,
        "human_approval_required": True,
    }


def _build_subject(target: dict) -> dict:
    return {en: to_json_safe(target.get(ja)) for ja, en in _SUBJECT_FIELD_MAP}


def _build_scope(scope_log: dict, raw_case_count) -> dict:
    scope_log = scope_log or {}
    return {
        "raw_case_count": to_json_safe(raw_case_count),
        "scoped_case_count": to_json_safe(scope_log.get("final_count")),
        "comparison_candidate_count": to_json_safe(scope_log.get("comparison_recent_count")),
        "target_city": to_json_safe(scope_log.get("target_city")),
        "period_years": to_json_safe(scope_log.get("period_years")),
        "comparison_period_months": to_json_safe(DEFAULT_COMPARISON_MONTHS),
        "jijo_removed_count": to_json_safe(scope_log.get("jijo_removed")),
        "iqr_removed_count": to_json_safe(scope_log.get("iqr_removed")),
        "warnings": to_json_safe(scope_log.get("warnings") or []),
    }


def _build_time_adjustment(rate_info: dict) -> dict:
    rate_info = rate_info or {}
    selected_points = []
    for p in rate_info.get("selected_points") or []:
        selected_points.append({
            "id": to_json_safe(p.get("id")),
            "source": to_json_safe(p.get("source")),
            "district": to_json_safe(p.get("district")),
            "rate": _round_rate(p.get("rate")),
            "p_prev": to_json_safe(p.get("p_prev")),
            "p_curr": to_json_safe(p.get("p_curr")),
            "date_prev": to_json_safe(p.get("date_prev")),
            "date_curr": to_json_safe(p.get("date_curr")),
        })
    return {
        "annual_rate": _round_rate(rate_info.get("rate")),
        "n_points": to_json_safe(rate_info.get("n_points")),
        "source": to_json_safe(rate_info.get("source")),
        "method": to_json_safe(rate_info.get("method")),
        "selected_points": selected_points,
    }


def _build_hedonic(hed: dict, prediction_unit_price) -> dict:
    hed = hed or {}
    coefficients = {}
    for name, c in (hed.get("coefficients") or {}).items():
        coefficients[name] = {
            "beta": _round_rate(c.get("beta")),
            "se": _round_rate(c.get("se")),
            "p": _round_rate(c.get("p")),
            "label": to_json_safe(c.get("label")),
        }
    return {
        "ok": bool(hed.get("ok")),
        "n": to_json_safe(hed.get("n")),
        "adjusted_r2": _round_rate(hed.get("adj_r2")),
        "skip_reason": to_json_safe(hed.get("skip_reason")),
        "prediction_unit_price": _round_money(prediction_unit_price),
        "coefficients": coefficients,
    }


def _build_comparables(cases_df) -> list:
    out = []
    if cases_df is None:
        return out
    for i, (_, row) in enumerate(cases_df.iterrows()):
        out.append({
            "rank": i + 1,
            "case_no": to_json_safe(row.get("case_no")),
            "district": to_json_safe(row.get("district")),
            "transaction_date": to_json_safe(row.get("transaction_date")),
            "unit_price": _round_money(row.get("unit_price")),
            "area": to_json_safe(row.get("area")),
            "station": to_json_safe(row.get("station")),
            "station_walk_min": to_json_safe(row.get("walk_min")),
            "road_type": to_json_safe(row.get("road_type")),
            "road_width_m": to_json_safe(row.get("road_width")),
            "road_direction": to_json_safe(row.get("road_dir")),
            "shape": to_json_safe(row.get("shape")),
            "similarity": _round_rate(row.get("similarity")),
            "corrected_unit_price": _round_money(row.get("corrected_unit_price")),
        })
    return out


def _build_assessment(assessment: dict) -> dict:
    assessment = assessment or {}
    rng = assessment.get("range") or {}
    return {
        "method": to_json_safe(assessment.get("method")),
        "n_cases": to_json_safe(assessment.get("n_cases")),
        "adopted_unit_price": _round_money(assessment.get("central_unit_price")),
        "adopted_total_price": _round_money(assessment.get("central_total_price")),
        "price_range": {
            "low_unit_price": _round_money(rng.get("low_unit")),
            "central_unit_price": _round_money(rng.get("central_unit")),
            "high_unit_price": _round_money(rng.get("high_unit")),
            "low_total_price": _round_money(rng.get("low_total")),
            "central_total_price": _round_money(rng.get("central_total")),
            "high_total_price": _round_money(rng.get("high_total")),
        },
        "warning": to_json_safe(assessment.get("warning")),
    }


def _build_warnings(scope_log: dict, assessment: dict, hed: dict) -> list:
    scope_log = scope_log or {}
    assessment = assessment or {}
    hed = hed or {}
    warnings = []
    for w in scope_log.get("warnings") or []:
        if w not in warnings:
            warnings.append(w)
    w = assessment.get("warning")
    if w and w not in warnings:
        warnings.append(w)
    if not hed.get("ok"):
        skip_reason = hed.get("skip_reason")
        if skip_reason and skip_reason not in warnings:
            warnings.append(skip_reason)
    return to_json_safe(warnings)


def build_result(ctx: dict) -> dict:
    """ctx（既存パイプラインの正本）から公開用 JSON 結果を組み立てる。計算は行わない。"""
    target = ctx["target"]
    asof = ctx.get("asof")
    scope_log = ctx.get("scope_log") or {}
    rate_info = ctx.get("rate_info") or {}
    hed = ctx.get("hedonic") or {}
    cases = ctx.get("cases")
    assessment = ctx.get("assess") or {}
    hed_pred = (ctx.get("refs") or {}).get("hedonic_pred")
    raw_case_count = ctx.get("raw_case_count")

    return {
        "schema_version": SCHEMA_VERSION,
        "engine": _build_engine(),
        "valuation_status": _build_valuation_status(),
        "subject": _build_subject(target),
        "valuation_date": asof.isoformat() if asof else None,
        "scope": _build_scope(scope_log, raw_case_count),
        "time_adjustment": _build_time_adjustment(rate_info),
        "hedonic": _build_hedonic(hed, hed_pred),
        "comparables": _build_comparables(cases),
        "assessment": _build_assessment(assessment),
        "warnings": _build_warnings(scope_log, assessment, hed),
    }


def write_json(ctx: dict, output_path) -> Path:
    """ctx から決定的 JSON を組み立て、output_path へ UTF-8 で書き出す。

    失敗時は途中ファイルを残さない（一時ファイルへ書いてから置換）。
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = build_result(ctx)
    tmp_path = output_path.with_name(output_path.name + ".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            f.write("\n")
        tmp_path.replace(output_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return output_path
