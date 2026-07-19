import math
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from correction import apply_correction, hijun_correction_for_case
from hedonic import _build_features
from load_mlit import load_mlit_csv
from time_adjust import annual_rate_for_city


def _hedonic(beta_by_feature):
    return {
        "ok": True,
        "coefficients": {
            name: {"beta": beta, "se": 0.0, "p": 0.0, "label": name}
            for name, beta in beta_by_feature.items()
        },
        "feature_defaults": {"kanguchi": 6.0, "walk_min": 10.0, "road_width": 6.0, "floor_area_ratio": 200.0},
    }


def _case(**kwargs):
    base = {
        "unit_price": 1_000_000.0,
        "adjusted_unit_price": 1_000_000.0,
        "area": math.e,
        "walk_min": 10.0,
        "kanguchi": 6.0,
        "road_width": 6.0,
        "floor_area_ratio": 200.0,
        "road_dir": "北",
        "shape": "整形",
        "road_type": "公道",
    }
    base.update(kwargs)
    return pd.DataFrame([base])


def test_correction_direction_fixed_expected_value():
    target = {"面積(㎡)": math.e**2, "間口": 6.0, "最寄駅:距離(分)": 10}
    actual = apply_correction(_case(), _hedonic({"ln_area": 0.1}), target).iloc[0]["corrected_unit_price"]
    expected = 1_000_000 * math.exp(0.1 * (2 - 1))
    assert actual == pytest.approx(expected)
    assert actual != pytest.approx(1_000_000 / math.exp(0.1 * (2 - 1)))


def test_apply_correction_and_hijun_use_same_price_series():
    target = {"面積(㎡)": math.e**2, "間口": 6.0, "最寄駅:距離(分)": 10}
    corrected = apply_correction(_case(), _hedonic({"ln_area": 0.1}), target)
    assert corrected["canonical_case_price"].equals(corrected["corrected_unit_price"])
    h = hijun_correction_for_case(corrected.iloc[0], _hedonic({"ln_area": 0.1}), target)
    assert h["正本補正後単価"] == pytest.approx(corrected.iloc[0]["corrected_unit_price"])
    assert h["試算値"] == pytest.approx(round(corrected.iloc[0]["corrected_unit_price"], -4), abs=10_000)


def test_canonical_case_price_is_backward_compatible_alias_for_all_rows():
    target = {"面積(㎡)": math.e**2, "間口": 6.0, "最寄駅:距離(分)": 10}
    cases = pd.concat([
        _case(unit_price=1_000_000.0, adjusted_unit_price=1_000_000.0),
        _case(unit_price=1_200_000.0, adjusted_unit_price=1_250_000.0),
    ], ignore_index=True)
    corrected = apply_correction(cases, _hedonic({"ln_area": 0.1}), target)
    assert (corrected["canonical_case_price"] == corrected["corrected_unit_price"]).all()


def test_dir_score_and_fuseikei_are_not_double_counted():
    target = {"面積(㎡)": math.e, "前面道路:方位": "南", "土地の形状": "不整形"}
    hed = _hedonic({"dir_score": 0.1, "D_fuseikei": -0.2})
    actual = apply_correction(_case(road_dir="北", shape="整形"), hed, target).iloc[0]["corrected_unit_price"]
    contrib = 0.1 * (4 - 0) + (-0.2) * (1 - 0)
    assert actual == pytest.approx(1_000_000 * math.exp(contrib))
    assert actual != pytest.approx(1_000_000 * math.exp(2 * contrib))


def test_time_adjustment_evidence_uses_same_two_points_as_rate():
    koji = pd.DataFrame([
        {"標準地番号": "A", "city": "X市", "district": "D", "price_date": date(2024, 1, 1), "price_per_sqm": 100},
        {"標準地番号": "A", "city": "X市", "district": "D", "price_date": date(2025, 1, 1), "price_per_sqm": 110},
        {"標準地番号": "A", "city": "X市", "district": "D", "price_date": date(2026, 1, 1), "price_per_sqm": 220},
    ])
    info = annual_rate_for_city(koji, pd.DataFrame(), "X市", asof=date(2025, 6, 30))
    pt = info["selected_points"][0]
    assert pt["p_prev"] == 100
    assert pt["p_curr"] == 110
    assert pt["date_prev"] == date(2024, 1, 1)
    assert pt["date_curr"] == date(2025, 1, 1)


def test_time_adjustment_does_not_fallback_to_future_data():
    koji = pd.DataFrame([
        {"標準地番号": "A", "city": "X市", "district": "D", "price_date": date(2025, 1, 1), "price_per_sqm": 100},
        {"標準地番号": "A", "city": "X市", "district": "D", "price_date": date(2026, 1, 1), "price_per_sqm": 200},
    ])
    info = annual_rate_for_city(koji, pd.DataFrame(), "X市", asof=date(2025, 6, 30))
    assert info["rate"] is None
    assert info["selected_points"] == []


def test_mlit_loader_excludes_land_with_building(tmp_path):
    path = tmp_path / "mlit.csv"
    pd.DataFrame([
        {"種類": "宅地(土地)", "市区町村名": "X市", "地区名": "D", "取引価格(総額)": 1000, "面積(㎡)": 10, "取引価格(㎡単価)": None, "取引時点": "2025年第1四半期", "前面道路:種類": "市道"},
        {"種類": "宅地(土地と建物)", "市区町村名": "X市", "地区名": "D", "取引価格(総額)": 9999, "面積(㎡)": 10, "取引価格(㎡単価)": None, "取引時点": "2025年第1四半期", "前面道路:種類": "市道"},
    ]).to_csv(path, index=False, encoding="utf-8-sig")
    loaded = load_mlit_csv(path)
    assert len(loaded) == 1
    assert loaded.iloc[0]["unit_price"] == 100


def test_build_features_without_walk_min_column_uses_default():
    X = _build_features(pd.DataFrame([{"area": 100.0}]))
    assert X.iloc[0]["walk_min"] == 10.0
