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

"""類似度スコア計算と top 事例抽出。

スコア式: score = 1 - normalized_distance
  normalized_distance = w_g·d_geo + w_a·d_area + w_s·d_station + w_r·d_road + w_f·d_form

重みは経験則初期値、データで再検証可能（プラン §6.1）。
"""
import math
import pandas as pd

# 重み（プラン確定値、経験則初期値）
WEIGHTS = {
    "geo": 0.30,
    "area": 0.20,
    "station": 0.20,
    "road": 0.15,
    "form": 0.15,
}

DEFAULT_TOP_K = 5


def _d_geo(target_city, target_district, row):
    """地区距離: 同地区=0 / 同市区町村=0.3 / 隣接=0.6 / 他=1.0"""
    if row["city"] == target_city:
        if row.get("district") == target_district:
            return 0.0
        return 0.3
    return 0.6


def _d_area(target_area, row, max_log_diff):
    if max_log_diff <= 0:
        return 0.0
    diff = abs(math.log(row["area"]) - math.log(target_area))
    return min(diff / max_log_diff, 1.0)


def _d_station(target_walk, row):
    if pd.isna(row.get("walk_min")):
        return 0.5
    diff = abs(row["walk_min"] - target_walk)
    return min(diff / 30.0, 1.0)


def _d_road(target, row):
    """道路: 幅員差を /10 で正規化、方位一致で割引。"""
    target_width = target.get("前面道路:幅員(m)", 6.0)
    target_dir = target.get("前面道路:方位", "")
    width_d = 0.5
    if pd.notna(row.get("road_width")) and target_width is not None:
        width_d = min(abs(row["road_width"] - target_width) / 10.0, 1.0)
    dir_d = 0.0 if row.get("road_dir") == target_dir else 0.5
    return 0.7 * width_d + 0.3 * dir_d


def _d_form(target_shape, row):
    """形状: 同一=0 / 整形系同士=0.3 / 不整形系同士=0.5 / 整形⇄袋地=1.0"""
    rs = row.get("shape", "")
    if rs == target_shape:
        return 0.0
    pairs = {
        ("整形", "不整形"): 0.5, ("不整形", "整形"): 0.5,
        ("整形", "袋地"): 1.0, ("袋地", "整形"): 1.0,
        ("不整形", "袋地"): 0.5, ("袋地", "不整形"): 0.5,
    }
    return pairs.get((target_shape, rs), 0.5)


def compute_similarity(df: pd.DataFrame, target: dict) -> pd.DataFrame:
    """全事例に対して類似度スコアを計算し、similarity 列を付与した DataFrame を返す。"""
    if len(df) == 0:
        return df.assign(similarity=[])
    target_city = target["市区町村名"]
    target_district = target.get("地区名", "")
    target_area = target["面積(㎡)"]
    target_walk = target.get("最寄駅:距離(分)", 10)
    target_shape = target.get("土地の形状", "整形")

    log_areas = df["area"].apply(math.log)
    max_log_diff = (log_areas - math.log(target_area)).abs().max()
    if max_log_diff == 0 or pd.isna(max_log_diff):
        max_log_diff = 1.0

    distances = []
    for _, row in df.iterrows():
        d = (
            WEIGHTS["geo"] * _d_geo(target_city, target_district, row)
            + WEIGHTS["area"] * _d_area(target_area, row, max_log_diff)
            + WEIGHTS["station"] * _d_station(target_walk, row)
            + WEIGHTS["road"] * _d_road(target, row)
            + WEIGHTS["form"] * _d_form(target_shape, row)
        )
        distances.append(d)
    out = df.copy()
    out["distance"] = distances
    out["similarity"] = 1.0 - out["distance"]
    return out


def top_k(df_with_similarity: pd.DataFrame, k: int = DEFAULT_TOP_K) -> pd.DataFrame:
    """類似度上位 k 件を返す。"""
    return df_with_similarity.nlargest(k, "similarity").reset_index(drop=True)


if __name__ == "__main__":
    from pathlib import Path
    from datetime import date
    import json
    from load_mlit import load_mlit_csv
    from scope import scope_dataframe

    here = Path(__file__).parent.parent / "samples"
    df = load_mlit_csv(here / "sample_mlit.csv")
    with open(here / "sample_property.json", encoding="utf-8") as f:
        target = json.load(f)
    scoped, _ = scope_dataframe(df, target, date(2025, 12, 1))
    sim = compute_similarity(scoped, target)
    top = top_k(sim, 5)
    print(top[["district", "area", "walk_min", "shape", "unit_price", "similarity"]])
