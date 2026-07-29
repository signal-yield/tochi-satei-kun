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

"""ヘドニック回帰（対数線形 OLS）。
被説明変数: ln(adjusted_unit_price)  ※時点修正後の単価
特徴量: ln(面積), 駅徒歩分, D_私道, D_袋地, D_不整形

確定方針（プラン §2-1）：都度回帰、固定値ではない。
件数判定は scope.py 側で警告ログを付与するが、最終判定は呼び出し側。
"""
import math
import pandas as pd
import statsmodels.api as sm
from feature_defaults import DEFAULT_FAR, DEFAULT_FRONTAGE, DEFAULT_ROAD_WIDTH, DEFAULT_WALK_MIN

MIN_SAMPLES_FOR_REGRESSION = 15

# 方位スコア：北を 0、南を 4 とする ordinal scale（鑑定実務に親和的）
# 標準化補正で「北 → 南」の差分が綺麗に積算できる
DIR_SCORE = {
    "北": 0,
    "北東": 1, "北西": 1,
    "東": 2, "西": 2,
    "南東": 3, "南西": 3,
    "南": 4,
}

# 後方互換のため南向きセットも保持
SOUTH_FACING = {"南", "南東", "南西"}

# 特徴量 → SKILL.md/業者用シートで使う日本語名のマッピング
FEATURE_LABELS = {
    "ln_area": "面積",
    "ln_area_sq": "面積²",
    "walk_min": "駅徒歩分",
    "ln_shape": "形状指数",
    "ln_road_w": "道路幅員",
    "ln_far": "容積率",
    "dir_score": "方位",
    "D_shidou": "私道",
    "D_fukuro": "袋地",
    "D_fuseikei": "不整形",
    "ln_district_mean": "地区平均単価",
    "ln_station_mean": "駅勢圏平均単価",
    "const": "定数項",
}

# 地区／駅平均単価特徴量を有効にする最低サンプル数（地区／駅内）
DISTRICT_MEAN_MIN_SAMPLES = 3
STATION_MEAN_MIN_SAMPLES = 3


def _build_features(df: pd.DataFrame, feature_defaults: dict = None) -> pd.DataFrame:
    """特徴量行列を構築。MLIT既存項目を可能な限り活用。

    注：間口は単独では誤解を招く（広くても面積小さければ帯地）ため、
    形状指数 ln(間口²/面積) = 2*ln(間口) - ln(面積) として扱う。
    値0付近で正方形、正で横長（帯）、負で縦長（旗竿）。
    """
    feature_defaults = feature_defaults or {}
    default_walk = float(feature_defaults.get("walk_min", DEFAULT_WALK_MIN))
    default_frontage = float(feature_defaults.get("kanguchi", DEFAULT_FRONTAGE))
    default_road_width = float(feature_defaults.get("road_width", DEFAULT_ROAD_WIDTH))
    default_far = float(feature_defaults.get("floor_area_ratio", DEFAULT_FAR))
    X = pd.DataFrame(index=df.index)
    X["ln_area"] = df["area"].apply(math.log)
    # 面積²（規模逓減項）：大規模化で単価が下がる傾向を捕捉
    X["ln_area_sq"] = X["ln_area"] ** 2
    if "walk_min" in df.columns:
        walk = pd.to_numeric(df["walk_min"], errors="coerce")
        median = walk.median() if walk.notna().any() else default_walk
        X["walk_min"] = walk.fillna(median)
    else:
        X["walk_min"] = default_walk
    # 形状指数 = ln(間口²/面積) = 2·ln(間口) - ln(面積)
    if "kanguchi" in df.columns:
        kang = pd.to_numeric(df["kanguchi"], errors="coerce")
        kang_med = kang.median() if kang.notna().any() else default_frontage
        kang = kang.fillna(kang_med).clip(lower=0.5)
        X["ln_shape"] = 2 * kang.apply(math.log) - X["ln_area"]
    else:
        X["ln_shape"] = 2 * math.log(max(default_frontage, 0.5)) - X["ln_area"]
    # 道路幅員（対数、欠損は中央値で補完）
    if "road_width" in df.columns:
        rw = pd.to_numeric(df["road_width"], errors="coerce")
        rw_med = rw.median() if rw.notna().any() else default_road_width
        rw = rw.fillna(rw_med).clip(lower=1.0)
        X["ln_road_w"] = rw.apply(math.log)
    else:
        X["ln_road_w"] = math.log(max(default_road_width, 1.0))
    # 方位スコア（北=0、南=4 の ordinal）
    X["dir_score"] = df.get("road_dir", pd.Series([""] * len(df))).apply(
        lambda v: DIR_SCORE.get(str(v).strip(), 0)
    ).astype(float)
    # 容積率（対数）：行政条件として地価に直接影響（密度・収益上限）
    if "floor_area_ratio" in df.columns:
        far = pd.to_numeric(df["floor_area_ratio"], errors="coerce")
        far_med = far.median() if far.notna().any() else default_far
        far = far.fillna(far_med).clip(lower=1.0)
        X["ln_far"] = far.apply(math.log)
    else:
        X["ln_far"] = math.log(max(default_far, 1.0))
    # 既存ダミー
    road_type = df["road_type"] if "road_type" in df.columns else pd.Series([""] * len(df), index=df.index)
    shape = df["shape"] if "shape" in df.columns else pd.Series([""] * len(df), index=df.index)
    X["D_shidou"] = (road_type == "私道").astype(int)
    X["D_fukuro"] = (shape == "袋地").astype(int)
    X["D_fuseikei"] = (shape == "不整形").astype(int)
    # 地区／駅平均単価（ターゲット符号化）：annotate_*_mean で事前に df に
    # ln_district_mean / ln_station_mean 列を付与しておく前提
    if "ln_district_mean" in df.columns:
        X["ln_district_mean"] = df["ln_district_mean"]
    if "ln_station_mean" in df.columns:
        X["ln_station_mean"] = df["ln_station_mean"]
    return X


def annotate_district_mean(df: pd.DataFrame) -> pd.DataFrame:
    """df に ln_district_mean 列を追加。

    地区別の単価平均を ln 取って格納。地区内 n >= DISTRICT_MEAN_MIN_SAMPLES なら
    同地区平均、それ未満は市区町村全体平均で代用。
    """
    out = df.copy()
    if "district" not in out.columns or "unit_price" not in out.columns or len(out) == 0:
        return out
    price_col = "adjusted_unit_price" if "adjusted_unit_price" in out.columns else "unit_price"
    price = pd.to_numeric(out[price_col], errors="coerce")
    group_sum = price.groupby(out["district"]).transform("sum")
    group_count = price.groupby(out["district"]).transform("count")
    overall_sum = price.sum()
    overall_count = price.notna().sum()
    loo_count = group_count - 1
    district_price = (group_sum - price) / loo_count
    overall_loo = (overall_sum - price) / (overall_count - 1) if overall_count > 1 else price.mean()
    district_price = district_price.where(loo_count >= DISTRICT_MEAN_MIN_SAMPLES - 1, overall_loo)
    out["ln_district_mean"] = district_price.clip(lower=1.0).apply(math.log)
    return out


def annotate_station_mean(df: pd.DataFrame) -> pd.DataFrame:
    """df に ln_station_mean 列を追加。

    最寄駅別の単価平均を ln 取って格納。駅内 n >= STATION_MEAN_MIN_SAMPLES なら
    同駅平均、それ未満は市区町村全体平均で代用。
    """
    out = df.copy()
    if "station" not in out.columns or "unit_price" not in out.columns or len(out) == 0:
        return out
    price_col = "adjusted_unit_price" if "adjusted_unit_price" in out.columns else "unit_price"
    price = pd.to_numeric(out[price_col], errors="coerce")
    group_sum = price.groupby(out["station"]).transform("sum")
    group_count = price.groupby(out["station"]).transform("count")
    overall_sum = price.sum()
    overall_count = price.notna().sum()
    loo_count = group_count - 1
    station_price = (group_sum - price) / loo_count
    overall_loo = (overall_sum - price) / (overall_count - 1) if overall_count > 1 else price.mean()
    station_price = station_price.where(loo_count >= STATION_MEAN_MIN_SAMPLES - 1, overall_loo)
    out["ln_station_mean"] = station_price.clip(lower=1.0).apply(math.log)
    return out


def _median_default(df: pd.DataFrame, col: str, fallback: float) -> float:
    if col not in df.columns:
        return fallback
    s = pd.to_numeric(df[col], errors="coerce")
    return float(s.median()) if s.notna().any() else fallback


def fit_hedonic(df: pd.DataFrame) -> dict:
    """対数線形回帰を実行し、結果辞書を返す。

    Returns:
        {
          "ok": bool,
          "n": int,
          "r2": float, "adj_r2": float,
          "coefficients": {feature_name: {"beta": float, "se": float, "p": float, "label": str}},
          "skip_reason": str (if not ok),
        }
    """
    n = len(df)
    if n < MIN_SAMPLES_FOR_REGRESSION:
        return {
            "ok": False, "n": n, "r2": None, "adj_r2": None,
            "coefficients": {},
            "skip_reason": f"件数 {n} < {MIN_SAMPLES_FOR_REGRESSION}: 回帰スキップ",
        }
    if "ln_adjusted_unit_price" not in df.columns:
        y = df["unit_price"].apply(math.log)
    else:
        y = df["ln_adjusted_unit_price"]
    feature_defaults = {
        "walk_min": _median_default(df, "walk_min", DEFAULT_WALK_MIN),
        "kanguchi": _median_default(df, "kanguchi", DEFAULT_FRONTAGE),
        "road_width": _median_default(df, "road_width", DEFAULT_ROAD_WIDTH),
        "floor_area_ratio": _median_default(df, "floor_area_ratio", DEFAULT_FAR),
    }
    X = _build_features(df, feature_defaults)
    X = sm.add_constant(X)
    try:
        model = sm.OLS(y, X).fit()
    except Exception as e:
        return {
            "ok": False, "n": n, "r2": None, "adj_r2": None,
            "coefficients": {},
            "skip_reason": f"OLS失敗: {e}",
        }

    coef = {}
    for name in X.columns:
        coef[name] = {
            "beta": float(model.params[name]),
            "se": float(model.bse[name]),
            "p": float(model.pvalues[name]),
            "label": FEATURE_LABELS.get(name, name),
        }
    return {
        "ok": True, "n": n,
        "r2": float(model.rsquared),
        "adj_r2": float(model.rsquared_adj),
        "coefficients": coef,
        "feature_defaults": feature_defaults,
        "skip_reason": None,
    }


if __name__ == "__main__":
    from pathlib import Path
    from datetime import date
    import json
    from load_mlit import load_mlit_csv, load_koji_csv, load_kijun_csv
    from scope import scope_dataframe
    from time_adjust import annual_rate_for_city, apply_time_adjustment

    here = Path(__file__).parent.parent / "samples"
    df = load_mlit_csv(here / "sample_mlit.csv")
    koji = load_koji_csv(here / "sample_koji.csv")
    kijun = load_kijun_csv(here / "sample_kijun.csv")
    with open(here / "sample_property.json", encoding="utf-8") as f:
        target = json.load(f)
    asof = date(2025, 12, 1)
    scoped, _ = scope_dataframe(df, target, asof)
    rate = annual_rate_for_city(koji, kijun, target["市区町村名"])["rate"]
    adjusted = apply_time_adjustment(scoped, asof, rate)
    result = fit_hedonic(adjusted)
    print(f"ok={result['ok']}, n={result['n']}, R²={result['r2']:.3f}")
    for name, c in result["coefficients"].items():
        print(f"  {name:15s}: β={c['beta']:+.4f} (se={c['se']:.4f}, p={c['p']:.3f})")
