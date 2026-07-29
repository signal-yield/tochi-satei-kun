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

"""比準価格集約と価格レンジ生成。

確定方針（プラン §6.2, §6.3）：
- 件数別の集約規則（trim_mean / median）
- 価格レンジは四分位ベース（Q1 / 中央/trim_mean / Q3）× 面積
"""
import numpy as np
import pandas as pd

TRIM_PROPORTION = 0.10  # 上下10%カット


def _trim_mean(values, proportion=TRIM_PROPORTION):
    arr = np.array(values, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) == 0:
        return None
    arr = np.sort(arr)
    cut = int(len(arr) * proportion)
    if cut > 0:
        arr = arr[cut:-cut]
    return float(arr.mean()) if len(arr) > 0 else None


def aggregate_unit_price(corrected_prices) -> dict:
    """件数別の集約規則を適用し、代表単価を返す。"""
    arr = np.array([v for v in corrected_prices if v is not None and not np.isnan(v)])
    n = len(arr)
    log = {"n": n, "method": None, "warning": None, "central": None}

    if n == 0:
        log["warning"] = "集約対象が0件"
        return log
    if n >= 10:
        log["method"] = f"trim_mean({int(TRIM_PROPORTION*100)}%)"
        log["central"] = _trim_mean(arr)
    elif n >= 5:
        log["method"] = "median"
        log["central"] = float(np.median(arr))
    elif n >= 3:
        log["method"] = "median"
        log["central"] = float(np.median(arr))
        log["warning"] = "件数が少なく信頼性に注意"
    else:
        log["method"] = "median"
        log["central"] = float(np.median(arr))
        log["warning"] = f"件数 {n} 件: 査定不能"
    return log


def price_range(corrected_prices, area: float, central_unit: float = None) -> dict:
    """四分位ベースの3レンジ（早期/適正/強気）× 面積。"""
    arr = np.array([v for v in corrected_prices if v is not None and not np.isnan(v)])
    if len(arr) == 0:
        return {"low_total": None, "central_total": None, "high_total": None,
                "low_unit": None, "central_unit": None, "high_unit": None}
    q1 = float(np.percentile(arr, 25))
    q3 = float(np.percentile(arr, 75))
    if central_unit is None:
        central_unit = _trim_mean(arr) if len(arr) >= 10 else float(np.median(arr))
    return {
        "low_unit": q1,
        "central_unit": central_unit,
        "high_unit": q3,
        "low_total": q1 * area,
        "central_total": central_unit * area,
        "high_total": q3 * area,
    }


def assess(corrected_df: pd.DataFrame, area: float) -> dict:
    """補正後事例DataFrameから査定結果を組み立てる。
    価格レンジは **top3 事例の試算値の min / median / max** を直接採用（比準表と整合）。
    """
    arr = [float(v) for v in corrected_df["corrected_unit_price"].tolist()
           if v is not None and not pd.isna(v)]
    n = len(arr)
    if n == 0:
        return {
            "central_unit_price": None, "central_total_price": None,
            "method": "事例なし", "warning": "集約対象が0件", "n_cases": 0,
            "range": {"low_unit": None, "central_unit": None, "high_unit": None,
                      "low_total": None, "central_total": None, "high_total": None},
        }
    arr_sorted = sorted(arr)
    high_unit = arr_sorted[-1]
    low_unit = arr_sorted[0]
    # 中央：奇数なら中央値、偶数なら中央2値の平均
    if n % 2 == 1:
        central_unit = arr_sorted[n // 2]
    else:
        central_unit = (arr_sorted[n // 2 - 1] + arr_sorted[n // 2]) / 2
    warning = None
    if n < 3:
        warning = f"事例件数 {n}件：価格レンジは参考程度"
    return {
        "central_unit_price": central_unit,
        "central_total_price": central_unit * area,
        "method": f"top{n}事例の中央値（比準表試算値と整合）",
        "warning": warning,
        "n_cases": n,
        "range": {
            "low_unit": low_unit,
            "central_unit": central_unit,
            "high_unit": high_unit,
            "low_total": low_unit * area,
            "central_total": central_unit * area,
            "high_total": high_unit * area,
        },
    }


def assess_top1(corrected_df: pd.DataFrame, area: float) -> dict:
    """流推方式準拠：最類似1件＋個別格差補正で査定価格、2-3位で価格レンジ生成。

    査定価格 = 主比準事例（top1）の補正後単価 × 面積
    価格レンジ:
      上限 = max(top1〜3 の補正後単価) × 面積
      中央 = top1 の補正後単価 × 面積（=査定価格）
      下限 = min(top1〜3 の補正後単価) × 面積
    """
    n = len(corrected_df)
    if n == 0:
        return {
            "central_unit_price": None, "central_total_price": None,
            "method": "top1比準", "warning": "事例なし", "n_cases": 0,
            "primary_case": None,
            "range": {"low_unit": None, "central_unit": None, "high_unit": None,
                      "low_total": None, "central_total": None, "high_total": None},
        }
    top1 = corrected_df.iloc[0]
    central_unit = float(top1["corrected_unit_price"])
    central_total = central_unit * area

    all_units = corrected_df["corrected_unit_price"].astype(float).tolist()
    high_unit = max(all_units)
    low_unit = min(all_units)

    warning = None
    if n < 3:
        warning = f"検証用事例不足（{n}件）：価格レンジは参考程度"

    return {
        "central_unit_price": central_unit,
        "central_total_price": central_total,
        "method": "top1比準（流推方式準拠）",
        "warning": warning,
        "n_cases": n,
        "primary_case": {
            "district": top1.get("district"),
            "area": float(top1["area"]),
            "transaction_date": str(top1["transaction_date"]),
            "similarity": float(top1.get("similarity", 0)),
            "original_unit_price": float(top1["unit_price"]),
            "adjusted_unit_price": float(top1.get("adjusted_unit_price", top1["unit_price"])),
            "corrected_unit_price": central_unit,
        },
        "range": {
            "low_unit": low_unit,
            "central_unit": central_unit,
            "high_unit": high_unit,
            "low_total": low_unit * area,
            "central_total": central_total,
            "high_total": high_unit * area,
        },
    }


if __name__ == "__main__":
    # ダミー値での動作確認
    dummy = [3_500_000, 3_700_000, 3_800_000, 4_000_000, 4_200_000, 4_400_000,
             4_500_000, 4_700_000, 4_900_000, 5_100_000, 5_300_000]
    print(aggregate_unit_price(dummy))
    print(price_range(dummy, 120))
