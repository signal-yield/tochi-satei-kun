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

"""時点修正：公示地価の **直近1年変動率** で、各事例の単価を査定時点に補正。

確定方針（2026-05-10 松田レビュー反映）：
- 標準地は **査定地と同地区を優先**（地区一致がなければ市区町村平均）
- 変動率は **直近1年（前年→当年）** を採用（CAGR ではない単純1年変動率）
- 複数標準地がある場合は変動率を単純平均
- **隣接市区町村への自動拡張は行わない**（市区町村単位を厳守、標準地なし時は rate=None で返す）
"""
from datetime import date
import math
import pandas as pd


def _annual_rate_per_standard_point(group: pd.DataFrame, asof: date = None) -> float:
    """単一標準地の **直近1年変動率** を返す。
    asof 以前で最新の2点（通常 前年1月1日 と 当年1月1日）から (P_t / P_{t-1})^(1/年差) - 1。
    """
    g = group.sort_values("price_date")
    if len(g) < 2:
        return None
    if asof is not None:
        sub = g[g["price_date"] <= asof]
        if len(sub) < 2:
            return None
    else:
        sub = g
    last2 = sub.tail(2)
    p_first = float(last2.iloc[0]["price_per_sqm"])
    p_last = float(last2.iloc[1]["price_per_sqm"])
    if p_first <= 0:
        return None
    days = (last2.iloc[1]["price_date"] - last2.iloc[0]["price_date"]).days
    if days <= 0:
        return None
    years = days / 365.25
    ratio = p_last / p_first
    if ratio <= 0:
        return None
    return ratio ** (1.0 / years) - 1.0


def _annual_rate_info_per_standard_point(group: pd.DataFrame, asof: date = None) -> dict:
    """Return rate and the exact two evidence points used for that rate."""
    g = group.sort_values("price_date")
    if asof is not None:
        g = g[g["price_date"] <= asof]
    if len(g) < 2:
        return {"rate": None, "skip_reason": "asof以前の標準地価格が2点未満"}
    last2 = g.tail(2)
    rate = _annual_rate_per_standard_point(last2, None)
    if rate is None:
        return {"rate": None, "skip_reason": "標準地価格の変動率を計算できません"}
    return {
        "rate": rate,
        "p_prev": float(last2.iloc[0]["price_per_sqm"]),
        "p_curr": float(last2.iloc[1]["price_per_sqm"]),
        "date_prev": last2.iloc[0]["price_date"],
        "date_curr": last2.iloc[1]["price_date"],
        "skip_reason": None,
    }


def _collect_rates(sub: pd.DataFrame, src_name: str, asof: date) -> list:
    """DataFrame から標準地ごとの1年変動率を集める。"""
    out = []
    if "標準地番号" not in sub.columns:
        return out
    for std_id, group in sub.groupby("標準地番号"):
        info = _annual_rate_info_per_standard_point(group, asof)
        if info["rate"] is not None:
            out.append({
                "id": std_id,
                "source": src_name,
                "district": group.iloc[0].get("district", ""),
                "rate": info["rate"],
                "p_prev": info["p_prev"],
                "p_curr": info["p_curr"],
                "date_prev": info["date_prev"],
                "date_curr": info["date_curr"],
            })
    return out


def annual_rate_for_city(koji: pd.DataFrame, kijun: pd.DataFrame, city: str,
                         target_district: str = None, asof: date = None) -> dict:
    """対象地区の標準地から **直近1年変動率の平均** を返す。地区一致優先。

    Returns:
        {
          "rate": float,
          "n_points": int,
          "source": "公示" or "公示+基準地",
          "method": "district_match" | "city_average" | "none",
          "expanded_to": list,  # 後方互換のため空配列を保持（隣接拡張は廃止）
          "selected_points": [{"id", "source", "district", "rate", "p_prev", "p_curr",
                                "date_prev", "date_curr"}],
        }
    """
    log = {"rate": None, "n_points": 0, "source": "none",
           "method": "none", "expanded_to": [], "selected_points": []}

    sources = []
    if koji is not None and not koji.empty:
        c_sub = koji[koji["city"] == city]
        if not c_sub.empty:
            sources.append(("公示", c_sub))
    if kijun is not None and not kijun.empty:
        k_sub = kijun[kijun["city"] == city]
        if not k_sub.empty:
            sources.append(("基準地", k_sub))

    if not sources:
        # 標準地なし：時点修正なしで返す（隣接拡張は行わない）
        return log

    selected = []
    method = "city_average"

    # ① 地区一致優先
    if target_district:
        for src_name, sub in sources:
            district_match = sub[sub["district"] == target_district]
            if not district_match.empty:
                selected.extend(_collect_rates(district_match, src_name, asof))
        if selected:
            method = "district_match"

    # ② 地区一致がなければ市区町村全体
    if not selected:
        for src_name, sub in sources:
            selected.extend(_collect_rates(sub, src_name, asof))

    if selected:
        rates_only = [p["rate"] for p in selected]
        log["rate"] = sum(rates_only) / len(rates_only)
        log["n_points"] = len(selected)
        log["source"] = "+".join(sorted(set(p["source"] for p in selected)))
        log["method"] = method
        log["selected_points"] = selected
    return log


def apply_time_adjustment(df: pd.DataFrame, asof: date, annual_rate: float) -> pd.DataFrame:
    """各事例の単価を asof 時点に補正。

    adjusted = original * (1 + rate) ** years_to_asof
    """
    if annual_rate is None:
        out = df.copy()
        out["years_to_asof"] = 0.0
        out["adjusted_unit_price"] = out["unit_price"]
        return out

    def _years(d):
        return (asof.year - d.year) + (asof.month - d.month) / 12.0

    out = df.copy()
    out["years_to_asof"] = out["transaction_date"].apply(_years)
    out["adjusted_unit_price"] = out.apply(
        lambda r: r["unit_price"] * ((1 + annual_rate) ** r["years_to_asof"]), axis=1
    )
    out["ln_adjusted_unit_price"] = out["adjusted_unit_price"].apply(math.log)
    return out


if __name__ == "__main__":
    from pathlib import Path
    import json
    from load_mlit import load_mlit_csv, load_koji_csv, load_kijun_csv
    from scope import scope_dataframe

    here = Path(__file__).parent.parent / "samples"
    df = load_mlit_csv(here / "sample_mlit.csv")
    koji = load_koji_csv(here / "sample_koji.csv")
    kijun = load_kijun_csv(here / "sample_kijun.csv")
    with open(here / "sample_property.json", encoding="utf-8") as f:
        target = json.load(f)
    asof = date(2025, 12, 1)
    scoped, _ = scope_dataframe(df, target, asof)
    rate_info = annual_rate_for_city(koji, kijun, target["市区町村名"])
    print(f"年率情報: {rate_info}")
    adjusted = apply_time_adjustment(scoped, asof, rate_info["rate"])
    print(adjusted[["district", "transaction_date", "unit_price",
                    "years_to_asof", "adjusted_unit_price"]].head(5))
