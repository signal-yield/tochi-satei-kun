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

"""比準表「補修正率と地域格差率」詳細内訳の計算（v1.2.9 で correction.py から切り出し）。

鑑定実務での 4 区分（標準化補正：規模・画地、地域格差：街路・交通接近・環境・行政）
への分解と、各細目の % 表示を生成する。correction.py 本体を 20KB 未満に圧縮し
Cowork 配布層の truncate を回避するため独立モジュール化。
"""
import math
import pandas as pd

# correction.py から型情報・特徴量定数・ヘルパーをインポート
from correction import (CORRECTION_FEATURES, HIJUN_DETAIL_GROUP, HIJUN_DETAIL_LABEL,
                        _target_feature_value, _case_feature_value)


def hijun_breakdown_detail(row, hedonic_result, target):
    """事例1件について「補修正率と地域格差率」表用の詳細内訳を計算。

    Returns:
        {
          "事情補正": (label, percent),   # 例: ("正常", 0.0)
          "時点修正_pct": float,           # +%（年率×経過年数）
          "建付減価": (label, percent),   # ("更地", None) etc.
          "規模": [(label, %), ...],       # 標準化補正配下の細目
          "画地": [(label, %), ...],
          "化正相乗積": int,               # 100 + 規模%和 + 画地%和（または積×100）
          "街路": [(label, %), ...],       # 地域格差配下
          "交通接近": [(label, %), ...],
          "環境": [(label, %), ...],
          "行政": [(label, %), ...],       # 現状は空（β未取得）
          "街路_総和": float,
          "交通接近_総和": float,
          "環境_総和": float,
          "行政_総和": float,
          "相乗積": int,                   # 地域格差4区分の積×100
        }
    """
    out = {
        "事情補正": ("正常", 0.0),
        "建付減価": ("更地", None),
        "規模": [], "画地": [],
        "街路": [], "交通接近": [], "環境": [], "行政": [],
    }
    # 時点修正：adjusted/unit_price から %に変換
    base = float(row["unit_price"])
    if "adjusted_unit_price" in row and pd.notna(row["adjusted_unit_price"]):
        time_mult = float(row["adjusted_unit_price"]) / base if base > 0 else 1.0
    else:
        time_mult = 1.0
    out["時点修正_pct"] = (time_mult - 1.0) * 100

    if not hedonic_result.get("ok"):
        out["化正相乗積"] = 100
        out["街路_総和"] = 0.0
        out["交通接近_総和"] = 0.0
        out["環境_総和"] = 0.0
        out["行政_総和"] = 0.0
        out["相乗積"] = 100
        return out

    # v1.2.1: Style B — 事例側の値のみラベルに付記。査定対象側の値は個別格差シートに転記される設計。
    # 方位は事例の道路方位「方位(南)」「方位(東)」、地区は事例の地区「地区(赤堤)」等。
    case_road_dir = str(row.get("road_dir", "")).strip()
    case_district = str(row.get("district", "")).strip()
    def _label_for(feat):
        base = HIJUN_DETAIL_LABEL.get(feat, feat)
        if feat == "dir_score" and case_road_dir:
            return f"{base}({case_road_dir})"
        if feat == "ln_district_mean" and case_district:
            return f"{base}({case_district})"
        return base

    coef = hedonic_result["coefficients"]
    # 標準化補正の細目
    hyojunka_log_total = 0.0
    # 規模（ln_area + ln_area_sq）は1項目に統合して表示
    kibo_log = 0.0
    for feat in ("ln_area", "ln_area_sq"):
        if feat in coef and feat in HIJUN_DETAIL_GROUP:
            beta = coef[feat]["beta"]
            tx = _target_feature_value(target, feat)
            cx = _case_feature_value(row, feat)
            contrib = beta * (tx - cx)
            kibo_log += contrib
            hyojunka_log_total += contrib
    kibo_pct = (math.exp(kibo_log) - 1.0) * 100
    if abs(round(kibo_pct, 1)) >= 0.05:
        out["規模"].append(("規模", kibo_pct))

    # 画地（形状、袋地、不整形、方位）は個別表示
    for feat in CORRECTION_FEATURES:
        if feat not in coef or feat not in HIJUN_DETAIL_GROUP:
            continue
        if feat in ("ln_area", "ln_area_sq"):
            continue  # 既に処理済
        group = HIJUN_DETAIL_GROUP[feat]
        if group != "画地":
            continue
        beta = coef[feat]["beta"]
        tx = _target_feature_value(target, feat)
        cx = _case_feature_value(row, feat)
        contrib = beta * (tx - cx)  # 対数空間の補正
        pct = (math.exp(contrib) - 1.0) * 100
        out[group].append((_label_for(feat), pct))
        hyojunka_log_total += contrib
    # 標準化補正の総和（相乗積）
    out["標準化補正_総和"] = (math.exp(hyojunka_log_total) - 1.0) * 100
    # 化正相乗積 = exp(Σ log) × 100（後方互換のため残す）
    out["化正相乗積"] = int(round(math.exp(hyojunka_log_total) * 100))

    # 地域格差の細目（4区分）
    chiiki_subgroups = ("街路", "交通接近", "環境", "行政")
    subgroup_log = {g: 0.0 for g in chiiki_subgroups}
    for feat in CORRECTION_FEATURES:
        if feat not in coef or feat not in HIJUN_DETAIL_GROUP:
            continue
        group = HIJUN_DETAIL_GROUP[feat]
        if group not in chiiki_subgroups:
            continue
        beta = coef[feat]["beta"]
        tx = _target_feature_value(target, feat)
        cx = _case_feature_value(row, feat)
        contrib = beta * (tx - cx)
        pct = (math.exp(contrib) - 1.0) * 100
        out[group].append((_label_for(feat), pct))
        subgroup_log[group] += contrib

    for g in chiiki_subgroups:
        out[f"{g}_総和"] = (math.exp(subgroup_log[g]) - 1.0) * 100
    out["相乗積"] = int(round(math.exp(sum(subgroup_log.values())) * 100))
    return out
