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

"""公示価格選定・時系列補間ヘルパー（v1.4.1 で main_helpers.py から分割）。

main_helpers.py が Cowork 配布層 truncate ライン（~17KB）を超えたため、
geo（地理・用途地域・スコアリング・ヘドニック予測）と koji（標準価格選定・時系列）の
2 ファイルに分離。本ファイルは後者を担当。

依存：main_helpers_geo._score_koji_point, _short_koji_id
"""
from datetime import date

from main_helpers_geo import _score_koji_point, _short_koji_id


def _interpolate_price_at_asof(rows, asof: date):
    """同一標準地の年次価格行から asof 時点の補間価格を返す（線形補間）。
    L01 GeoJSON は過去5年分（例：2022-01-01〜2026-01-01）の年次価格を保持。
    asof を挟む2点間で線形補間、範囲外は最も近い点の値を採用。
    """
    rows_sorted = sorted(rows, key=lambda r: r["price_date"])
    if len(rows_sorted) == 0:
        return None
    if len(rows_sorted) == 1:
        return float(rows_sorted[0]["price_per_sqm"])
    for i in range(len(rows_sorted) - 1):
        d1 = rows_sorted[i]["price_date"]
        d2 = rows_sorted[i + 1]["price_date"]
        if d1 <= asof <= d2:
            p1 = float(rows_sorted[i]["price_per_sqm"])
            p2 = float(rows_sorted[i + 1]["price_per_sqm"])
            span = (d2 - d1).days
            if span <= 0:
                return p1
            t = (asof - d1).days / span
            return p1 + (p2 - p1) * t
    # 外挿：最も近い点の価格
    if asof < rows_sorted[0]["price_date"]:
        return float(rows_sorted[0]["price_per_sqm"])
    return float(rows_sorted[-1]["price_per_sqm"])


def _standard_price_for_city(koji, kijun, city: str, asof: date,
                             target_district: str = None,
                             target: dict = None) -> dict:
    """標準地を地区一致優先で選定し、asof時点に時点補間して返す。

    Returns:
        {
            "standard_price_per_sqm": 補間後平均（円/㎡）,
            "source": "公示" or "公示+基準地",
            "selected_points": [{id, source, district, address, use, price_at_asof}],
            "selection_method": "district_match" | "city_average",
            "n_points": int,
        }
    """
    all_data = []
    for src_df, src_name in [(koji, "公示"), (kijun, "基準地")]:
        if src_df is None or src_df.empty:
            continue
        sub = src_df[src_df["city"] == city]
        if not sub.empty:
            all_data.append((src_name, sub))

    if not all_data:
        return {"standard_price_per_sqm": None, "source": None,
                "selected_points": [], "selection_method": "none", "n_points": 0}

    selected_points = []
    selection_method = "city_average"

    # ① 地区一致優先
    if target_district:
        for src_name, sub in all_data:
            district_match = sub[sub["district"] == target_district]
            if not district_match.empty:
                for std_id, group in district_match.groupby("標準地番号"):
                    rows = group.to_dict("records")
                    interp = _interpolate_price_at_asof(rows, asof)
                    if interp:
                        selected_points.append({
                            "id": std_id,
                            "source": src_name,
                            "district": rows[0]["district"],
                            "use": rows[0].get("use", ""),
                            "price_at_asof": interp,
                            "address": rows[0].get("address", ""),
                            "area_sqm": rows[0].get("area_sqm"),
                            "use_detail": rows[0].get("use_detail", ""),
                            "road_type": rows[0].get("road_type", ""),
                            "road_dir": rows[0].get("road_dir", ""),
                            "road_width": rows[0].get("road_width"),
                            "station": rows[0].get("station", ""),
                            "station_dist_m": rows[0].get("station_dist_m"),
                            "zoning": rows[0].get("zoning", ""),
                            "building_coverage": rows[0].get("building_coverage"),
                            "floor_area_ratio": rows[0].get("floor_area_ratio"),
                            "frontage_ratio": rows[0].get("frontage_ratio"),
                            "depth_ratio": rows[0].get("depth_ratio"),
                        })
                if selected_points:
                    selection_method = "district_match"

    # ② 地区一致がなければ市区町村全体
    if not selected_points:
        for src_name, sub in all_data:
            for std_id, group in sub.groupby("標準地番号"):
                rows = group.to_dict("records")
                interp = _interpolate_price_at_asof(rows, asof)
                if interp:
                    selected_points.append({
                        "id": std_id,
                        "source": src_name,
                        "district": rows[0]["district"],
                        "use": rows[0].get("use", ""),
                        "price_at_asof": interp,
                        "address": rows[0].get("address", ""),
                        "area_sqm": rows[0].get("area_sqm"),
                        "use_detail": rows[0].get("use_detail", ""),
                        "road_type": rows[0].get("road_type", ""),
                        "road_dir": rows[0].get("road_dir", ""),
                        "road_width": rows[0].get("road_width"),
                        "station": rows[0].get("station", ""),
                        "station_dist_m": rows[0].get("station_dist_m"),
                        "zoning": rows[0].get("zoning", ""),
                        "building_coverage": rows[0].get("building_coverage"),
                        "floor_area_ratio": rows[0].get("floor_area_ratio"),
                    })

    if not selected_points:
        return {"standard_price_per_sqm": None, "source": None,
                "selected_points": [], "selection_method": "none", "n_points": 0,
                "label": ""}

    # 1地点に絞る：対象物件と最も類似する地点を選定（用途地域+容積率+丁目スコアリング）
    if target is not None and len(selected_points) > 1:
        scored = [(p, _score_koji_point(p, target)) for p in selected_points]
        # スコア降順、同点なら price 中央値に近い順
        prices = sorted(p["price_at_asof"] for p in selected_points)
        median_p = prices[len(prices) // 2]
        scored.sort(key=lambda x: (-x[1], abs(x[0]["price_at_asof"] - median_p)))
        best = scored[0][0]
        best_score = scored[0][1]
        # スコア記録（業者用シートでの透明性のため）
        best = dict(best)
        best["similarity_score"] = best_score
        selected_points = [best]

    avg = selected_points[0]["price_at_asof"]
    sources = sorted(set(p["source"] for p in selected_points))
    return {
        "standard_price_per_sqm": avg,
        "source": "+".join(sources),
        "selected_points": selected_points,
        "selection_method": selection_method,
        "n_points": len(selected_points),
        "label": _label_for_standard_points(selected_points),
    }


def _label_for_standard_points(points: list) -> str:
    """選定された公示標準地のラベル生成（1地点なら番号、複数なら地点数）。
    例：「赤堤（13112-000-015）」「赤堤3地点平均」「3地点平均」
    """
    if not points:
        return ""
    used_ids = sorted(set(p.get("id", "") for p in points if p.get("id")))
    used_districts = sorted(set(p.get("district", "") for p in points if p.get("district")))
    if len(used_ids) == 1:
        short_id = _short_koji_id(used_ids[0])
        if used_districts:
            return f"{used_districts[0]}（{short_id}）"
        return f"標準地 {short_id}"
    if len(used_districts) == 1:
        return f"{used_districts[0]}{len(used_ids)}地点平均"
    if used_districts:
        return f"{len(used_ids)}地点平均（{'、'.join(used_districts)}）"
    return f"{len(used_ids)}地点平均"


def _compute_koji_timeseries(koji, city: str, district: str = None,
                              selected_ids: list = None) -> dict:
    """時点修正に使用した公示標準地の年次価格推移を返す（時点修正と整合）。

    selected_ids が指定されればその標準地のみで集計、なければ地区一致 → 市区町村平均で集計。

    Returns:
        {
          "data": [{"year": int, "price": float}, ...],
          "selected_ids": [str, ...],
          "label": "赤堤3地点平均" or "13112-000-015 単独" など
        }
    """
    empty = {"data": [], "selected_ids": [], "label": ""}
    if koji is None or koji.empty:
        return empty
    matched = koji[koji["city"] == city]
    if selected_ids and "標準地番号" in matched.columns:
        # 時点修正で使った標準地に絞る
        matched = matched[matched["標準地番号"].isin(selected_ids)]
    elif district:
        d_match = matched[matched["district"] == district]
        if len(d_match) > 0:
            matched = d_match
    if "price_date" not in matched.columns or "price_per_sqm" not in matched.columns:
        return empty
    m = matched.dropna(subset=["price_date", "price_per_sqm"]).copy()
    m["year"] = m["price_date"].apply(lambda d: d.year if d else None)
    yearly = m.dropna(subset=["year"]).groupby("year")["price_per_sqm"].mean().reset_index()
    yearly = yearly.sort_values("year")
    data = [{"year": int(row["year"]), "price": float(row["price_per_sqm"])}
            for _, row in yearly.iterrows()]
    used_ids = sorted(matched["標準地番号"].dropna().unique().tolist()) if "標準地番号" in matched.columns else []
    used_districts = sorted(matched["district"].dropna().unique().tolist()) if "district" in matched.columns else []
    # ラベル生成（短縮 ID を使用：13112-000-050 → 世田谷-50）
    if len(used_ids) == 1:
        label = _short_koji_id(used_ids[0])
    elif used_districts:
        label = f"{used_districts[0]}{len(used_ids)}地点平均" if len(used_districts) == 1 else f"{len(used_ids)}地点平均"
    else:
        label = f"{len(used_ids)}地点平均"
    return {"data": data, "selected_ids": used_ids, "label": label}
