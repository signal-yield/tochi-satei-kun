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

"""地理・用途地域・公示地点スコアリング・ヘドニック予測ヘルパー（v1.4.1 で main_helpers.py から分割）。

main_helpers.py が Cowork 配布層 truncate ライン（~17KB）を超えたため、
geo（地理・用途地域・スコアリング・ヘドニック予測）と koji（標準価格選定・時系列）の
2 ファイルに分離。本ファイルは前者を担当。

依存：hedonic.DIR_SCORE, math, pandas
"""
import math

from hedonic import DIR_SCORE


SOUTH_FACING = {"南", "南東", "南西"}

# 公示番号の市区町村コード → 短縮名
_CITY_CODE_TO_SHORT = {
    "13101": "千代田", "13102": "中央", "13103": "港", "13104": "新宿",
    "13105": "文京", "13106": "台東", "13107": "墨田", "13108": "江東",
    "13109": "品川", "13110": "目黒", "13111": "大田", "13112": "世田谷",
    "13113": "渋谷", "13114": "中野", "13115": "杉並", "13116": "豊島",
    "13117": "北", "13118": "荒川", "13119": "板橋", "13120": "練馬",
    "13121": "足立", "13122": "葛飾", "13123": "江戸川",
}


def _short_koji_id(std_id: str) -> str:
    """公示番号を「市区町村-連番」形式に短縮。例: '13112-000-050' → '世田谷-50'"""
    if not std_id:
        return ""
    parts = str(std_id).split("-")
    if len(parts) < 3:
        return str(std_id)
    city_short = _CITY_CODE_TO_SHORT.get(parts[0], parts[0])
    try:
        n = int(parts[2])
    except (TypeError, ValueError):
        n = parts[2]
    return f"{city_short}-{n}"


# 用途地域カテゴリ判定（公示地点と対象物件のマッチング用）
_ZONING_CATEGORIES = {
    "低専": ["低専", "低住", "1種低層", "2種低層", "１低", "２低", "1低", "2低"],
    "中高": ["中高", "1種中高", "2種中高", "1中", "2中", "１中", "２中"],
    "住居": ["1住居", "2住居", "１住居", "２住居", "準住居"],
    "近商": ["近隣商業", "近商"],
    "商業": ["商業"],
    "準工": ["準工業", "準工"],
    "工業": ["工業", "工専"],
}


def _zoning_category(z: str) -> str:
    """用途地域文字列をカテゴリに正規化（マッチング比較用）。"""
    if not z:
        return ""
    z = str(z).strip()
    for cat, names in _ZONING_CATEGORIES.items():
        if any(n in z for n in names):
            return cat
    return ""


def _normalize_chome(s: str) -> str:
    """丁目数字（全角・漢数字を含む）を半角数字に正規化。"""
    if not s:
        return ""
    s = str(s).replace("丁目", "")
    zen2han = str.maketrans("０１２３４５６７８９", "0123456789")
    s = s.translate(zen2han)
    kanji = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
             "六": "6", "七": "7", "八": "8", "九": "9", "十": "10"}
    for k, v in kanji.items():
        s = s.replace(k, v)
    # 末尾数字のみ残す
    import re
    m = re.search(r"(\d+)", s)
    return m.group(1) if m else ""


def _score_koji_point(pt: dict, target: dict) -> float:
    """公示地点と対象物件の類似度スコア（0〜1、高いほど類似）。
    重み: 用途地域カテゴリ一致 0.4 / 容積率近さ 0.3 / 丁目一致 0.3。
    """
    score = 0.0
    # ① 用途地域カテゴリ一致
    t_cat = _zoning_category(target.get("都市計画", ""))
    p_cat = _zoning_category(pt.get("zoning", ""))
    if t_cat and p_cat and t_cat == p_cat:
        score += 0.4

    # ② 容積率の近さ
    try:
        t_far = float(target.get("容積率(%)", 200) or 200)
        p_far_raw = pt.get("floor_area_ratio")
        if p_far_raw not in (None, "", "_"):
            p_far = float(p_far_raw)
            if t_far > 0 and p_far > 0:
                diff_ratio = abs(t_far - p_far) / max(t_far, p_far)
                score += 0.3 * (1.0 - min(diff_ratio, 1.0))
    except (TypeError, ValueError):
        pass

    # ③ 丁目一致
    t_chome = _normalize_chome(target.get("丁目", ""))
    p_chome = ""
    addr = str(pt.get("address", ""))
    if "丁目" in addr:
        before = addr.split("丁目")[0]
        # 「赤堤５」「赤堤五」「赤堤5」の末尾数字を取得
        p_chome = _normalize_chome(before[-3:])
    if t_chome and p_chome and t_chome == p_chome:
        score += 0.3

    return score


def _hedonic_population_predict(hed: dict, target: dict) -> float:
    """係数辞書から対象物件の母集団予測値を算出。"""
    if not hed["ok"]:
        return None
    coef = hed["coefficients"]
    ln_pred = 0.0
    for name, c in coef.items():
        if name == "const":
            ln_pred += c["beta"]
            continue
        if name == "ln_area":
            x = math.log(target["面積(㎡)"])
        elif name == "ln_area_sq":
            x = math.log(target["面積(㎡)"]) ** 2
        elif name == "ln_far":
            v = target.get("容積率(%)", 200)
            try:
                v = float(v)
            except (TypeError, ValueError):
                v = 200.0
            x = math.log(max(v, 1.0))
        elif name == "walk_min":
            x = float(target.get("最寄駅:距離(分)", 10))
        elif name == "ln_shape":
            kang = target.get("間口", 6.0)
            try:
                kang = float(kang)
            except (TypeError, ValueError):
                kang = 6.0
            area = float(target["面積(㎡)"])
            x = 2 * math.log(max(kang, 0.5)) - math.log(max(area, 1.0))
        elif name == "ln_road_w":
            v = target.get("前面道路:幅員(m)", 5.0)
            try:
                v = float(v)
            except (TypeError, ValueError):
                v = 5.0
            x = math.log(max(v, 1.0))
        elif name == "dir_score":
            x = float(DIR_SCORE.get(str(target.get("前面道路:方位", "")).strip(), 0))
        elif name == "D_shidou":
            x = 1.0 if target.get("前面道路:種類") == "私道" else 0.0
        elif name == "D_fukuro":
            x = 1.0 if target.get("土地の形状") == "袋地" else 0.0
        elif name == "D_fuseikei":
            x = 1.0 if target.get("土地の形状") == "不整形" else 0.0
        elif name == "ln_district_mean":
            v = target.get("_target_district_mean", 0.0)
            x = math.log(v) if v and v > 0 else 0.0
        elif name == "ln_station_mean":
            v = target.get("_target_station_mean", 0.0)
            x = math.log(v) if v and v > 0 else 0.0
        else:
            x = 0.0
        ln_pred += c["beta"] * x
    return math.exp(ln_pred)
