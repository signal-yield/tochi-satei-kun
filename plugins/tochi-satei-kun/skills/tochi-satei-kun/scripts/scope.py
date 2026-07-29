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

"""データ範囲スコープ規則。
市区町村絞り込み → 取引事情フィルタ → IQR外れ値除外。

**確定規則（2026-05-11 ハイブリッド設計）**
- 地区＝市区町村単位（隣接市区町村への自動拡張は行わない・全面禁止）
- **scope_dataframe 段階：MLIT全期間を採用**（ヘドニック係数推定 n を最大化、係数の標準誤差を縮小）
- **取引事例比準（top 3 選定）段階：直近1.5年（18ヶ月）に絞る**（filter_recent_for_comparison）
  → 最新の市場感を反映、鑑定実務の「比較事例は直近を優先」と整合
- 時点修正（公示直近1年変動率）で全事例を査定時点に揃える
- 取引事情あり（投売り・親子間・代物弁済等）は除外
- 件数15件未満ならヘドニック回帰スキップ
"""
from datetime import date
import pandas as pd

DEFAULT_PERIOD_YEARS = None  # ヘドニック用：期間フィルタなし（MLIT全期間採用）
DEFAULT_COMPARISON_MONTHS = 18  # 比準事例選定用：直近1.5年
MIN_COUNT = 15  # この件数を下回ると hedonic.py 側でスキップ判定


def filter_period(df: pd.DataFrame, asof: date, years=DEFAULT_PERIOD_YEARS) -> pd.DataFrame:
    """asof から years 年前までの取引に絞る。years=None なら期間フィルタなし（全期間採用）。"""
    if years is None:
        return df.copy()
    cutoff = date(asof.year - years, asof.month, 1)
    return df[df["transaction_date"] >= cutoff].copy()


def filter_recent_for_comparison(df: pd.DataFrame, asof: date,
                                 months: int = DEFAULT_COMPARISON_MONTHS) -> pd.DataFrame:
    """取引事例比準（類似度 top 3 選定）のために直近 months ヶ月に絞る。
    デフォルトは1.5年（18ヶ月）。最新の市場感を反映する目的。
    """
    cutoff_year = asof.year
    cutoff_month = asof.month - months
    while cutoff_month <= 0:
        cutoff_year -= 1
        cutoff_month += 12
    cutoff = date(cutoff_year, cutoff_month, 1)
    return df[df["transaction_date"] >= cutoff].copy()


def filter_iqr(df: pd.DataFrame, col: str = "unit_price", k: float = 1.5) -> pd.DataFrame:
    """IQR 法で外れ値を除外。"""
    if len(df) < 4:
        return df
    q1 = df[col].quantile(0.25)
    q3 = df[col].quantile(0.75)
    iqr = q3 - q1
    lo = q1 - k * iqr
    hi = q3 + k * iqr
    return df[(df[col] >= lo) & (df[col] <= hi)].copy()


def filter_jijo(df: pd.DataFrame) -> pd.DataFrame:
    """「取引の事情等」に記載があるものを除外。

    対象：投売り・親子間取引・代物弁済・隣地取引・調停・私的売買等の
    一般市場性を欠く取引。MLIT原データの「取引の事情等」列が空欄の取引のみを残す。
    """
    if "取引の事情等" not in df.columns:
        return df
    s = df["取引の事情等"]
    mask = s.isna() | (s.astype(str).str.strip() == "")
    return df[mask].copy()


def scope_dataframe(df: pd.DataFrame, target: dict, asof: date) -> tuple:
    """物件 target に対してスコープ規則を適用し、(scoped_df, scope_log) を返す。

    Returns:
        scoped_df: 絞り込み後 DataFrame
        scope_log: dict — 件数・警告フラグ
    """
    log = {
        "target_city": target["市区町村名"],
        "expanded_to": [],  # 後方互換のため空配列を保持（隣接拡張は廃止）
        "period_years": DEFAULT_PERIOD_YEARS,  # None = 期間フィルタなし
        "jijo_removed": 0,
        "iqr_removed": 0,
        "final_count": 0,
        "warnings": [],
    }
    target_city = target["市区町村名"]

    # ① 市区町村絞り込み（隣接拡張なし、期間フィルタなし＝MLIT全期間）
    sub = df[df["city"] == target_city].copy()
    sub = filter_period(sub, asof)

    # ② 取引事情あり（投売り・親子間取引・代物弁済等）を除外
    before_jijo = len(sub)
    sub = filter_jijo(sub)
    log["jijo_removed"] = before_jijo - len(sub)

    # ③ IQR 外れ値除外
    before_iqr = len(sub)
    sub = filter_iqr(sub, "unit_price")
    log["iqr_removed"] = before_iqr - len(sub)

    log["final_count"] = len(sub)
    if len(sub) < MIN_COUNT:
        log["warnings"].append(
            f"件数 {len(sub)} 件 < 最低 {MIN_COUNT} 件: ヘドニック回帰スキップ・類似度ベース集約に降格"
        )

    return sub.reset_index(drop=True), log


if __name__ == "__main__":
    from pathlib import Path
    import json
    from load_mlit import load_mlit_csv

    here = Path(__file__).parent.parent / "samples"
    df = load_mlit_csv(here / "sample_mlit.csv")
    with open(here / "sample_property.json", encoding="utf-8") as f:
        target = json.load(f)
    asof = date(2025, 12, 1)
    scoped, log = scope_dataframe(df, target, asof)
    print(f"scoped: {len(scoped)} rows")
    print(f"log: {log}")
