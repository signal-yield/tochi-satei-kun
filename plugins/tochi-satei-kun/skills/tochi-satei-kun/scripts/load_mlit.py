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

"""MLIT 取引価格情報 CSV / 公示地価 CSV(または GeoJSON) / 基準地価 CSV の読込・正規化。
実MLIT公式CSV（cp932エンコーディング、全角コロン・全角括弧）に対応。
"""
import json
import math
import re
from datetime import date
from pathlib import Path
import pandas as pd

# 全角→半角の列名正規化（cp932 CSV対応）
COLUMN_NORMALIZE = {
    "最寄駅：名称": "最寄駅:名称",
    "最寄駅：距離（分）": "最寄駅:距離(分)",
    "取引価格（総額）": "取引価格(総額)",
    "面積（㎡）": "面積(㎡)",
    "取引価格（㎡単価）": "取引価格(㎡単価)",
    "前面道路：方位": "前面道路:方位",
    "前面道路：種類": "前面道路:種類",
    "前面道路：幅員（ｍ）": "前面道路:幅員(m)",
    "前面道路：幅員(m)": "前面道路:幅員(m)",
    "建ぺい率（％）": "建ぺい率(%)",
    "容積率（％）": "容積率(%)",
    "取引時期": "取引時点",  # 実データは「取引時期」、内部は「取引時点」に統一
}

# MLIT列名 → 内部標準列名
MLIT_COLUMN_MAP = {
    "種類": "type",
    "価格情報区分": "price_info_type",
    "地域": "region",
    "市区町村コード": "city_code",
    "都道府県名": "prefecture",
    "市区町村名": "city",
    "地区名": "district",
    "最寄駅:名称": "station",
    "最寄駅:距離(分)": "walk_min",
    "取引価格(総額)": "total_price",
    "面積(㎡)": "area",
    "取引価格(㎡単価)": "unit_price",
    "土地の形状": "shape_raw",
    "間口": "kanguchi",
    "前面道路:方位": "road_dir",
    "前面道路:種類": "road_type_raw",
    "前面道路:幅員(m)": "road_width",
    "都市計画": "zoning",
    "建ぺい率(%)": "building_coverage",
    "容積率(%)": "floor_area_ratio",
    "取引時点": "transaction_quarter_str",
    "今後の利用目的": "use",
}

# 形状値の正規化（実MLITの値 → 内部3カテゴリ）
SHAPE_NORMALIZE = {
    "整形": "整形", "ほぼ整形": "整形",
    "ほぼ正方形": "整形", "正方形": "整形",
    "ほぼ長方形": "整形", "長方形": "整形",
    "不整形": "不整形",
    "ほぼ台形": "不整形", "台形": "不整形",
    "袋地等": "袋地", "袋地": "袋地",
    "旗竿状": "袋地", "旗竿地": "袋地",
}

# 道路種類の正規化（実MLITの値 → 公道/私道）
# 注：MLITの「道路」（曖昧値）は除外する。明示的な公道分類のみ採用。
ROAD_NORMALIZE = {
    "区道": "公道", "都道": "公道", "国道": "公道",
    "市道": "公道", "町道": "公道", "村道": "公道",
    "県道": "公道", "府道": "公道",
    "私道": "私道",
}
# MLITで明示分類されない値は除外対象（"道路"などの曖昧値）
ROAD_VALID_VALUES = set(ROAD_NORMALIZE.keys())


def _parse_quarter(s: str) -> date:
    """'2024年第3四半期' → date(2024, 7, 1)"""
    if not isinstance(s, str) or "年第" not in s:
        return None
    try:
        year_str, rest = s.split("年第")
        q = int(rest.replace("四半期", ""))
        month = {1: 1, 2: 4, 3: 7, 4: 10}[q]
        return date(int(year_str), month, 1)
    except (ValueError, KeyError):
        return None


def _to_num(v):
    if pd.isna(v) or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _read_csv_auto_encoding(path):
    """utf-8-sig → cp932 → shift_jis の順に自動判定して読み込む。"""
    last_err = None
    for enc in ["utf-8-sig", "cp932", "shift_jis"]:
        try:
            return pd.read_csv(path, encoding=enc)
        except (UnicodeDecodeError, UnicodeError) as e:
            last_err = e
            continue
    raise UnicodeError(f"CSV のエンコーディング判定失敗: {path} ({last_err})")


def load_mlit_csv(path) -> pd.DataFrame:
    """MLIT 取引価格情報 CSV を読み込み、内部標準列名の DataFrame を返す。
    宅地(土地)のみ採用し、建物込み取引は除外。単価欠損行は土地のみ行で安全に補完。
    実MLIT (cp932, 全角コロン・全角括弧) も自動対応。
    各行に CSV原本での行番号 (case_no = 1始まり) を付与し、比準表で識別子として使う。
    """
    df = _read_csv_auto_encoding(path)
    # CSV原本の行番号を事例識別子として保持（フィルタ後も維持される）
    df["case_no"] = df.index + 1
    # 列名を全角→半角に正規化
    df = df.rename(columns=COLUMN_NORMALIZE)
    # 内部標準列名へマッピング
    df = df.rename(columns=MLIT_COLUMN_MAP)
    # 必須列存在チェック
    required = ["type", "city", "area", "unit_price"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"MLIT CSV 必須列欠損: {missing}")
    # 土地のみ。建物込み総額を土地単価として混入させない。
    df = df[df["type"] == "宅地(土地)"].copy()
    # 価格情報区分（実MLITにあれば「不動産取引価格情報」のみ採用）
    if "price_info_type" in df.columns:
        df = df[df["price_info_type"] == "不動産取引価格情報"].copy()
    # 数値変換
    for col in ["walk_min", "total_price", "area", "unit_price",
                "kanguchi", "road_width", "building_coverage", "floor_area_ratio"]:
        if col in df.columns:
            df[col] = df[col].apply(_to_num)
    # 単価派生（宅地(土地)として確認済みの行のみ）
    if "total_price" in df.columns and "area" in df.columns:
        missing_unit = df["unit_price"].isna()
        safe_area = df["area"].notna() & (df["area"] > 0)
        safe_total = df["total_price"].notna() & (df["total_price"] > 0)
        df.loc[missing_unit & safe_area & safe_total, "unit_price"] = (
            df.loc[missing_unit & safe_area & safe_total, "total_price"]
            / df.loc[missing_unit & safe_area & safe_total, "area"]
        )
    df = df[df["unit_price"].notna() & (df["unit_price"] > 0)]
    df = df[df["area"].notna() & (df["area"] > 0)]
    # 形状の正規化
    if "shape_raw" in df.columns:
        df["shape"] = df["shape_raw"].map(SHAPE_NORMALIZE).fillna("不整形")
    elif "shape" not in df.columns:
        df["shape"] = "整形"
    # 道路種類の正規化（曖昧値"道路"は除外、明示分類のみ採用）
    if "road_type_raw" in df.columns:
        df = df[df["road_type_raw"].isin(ROAD_VALID_VALUES)].copy()
        df["road_type"] = df["road_type_raw"].map(ROAD_NORMALIZE)
    elif "road_type" not in df.columns:
        df["road_type"] = "公道"
    # 間口 ≤ 2m の事例を除外（建築基準法第43条・接道義務未達）
    if "kanguchi" in df.columns:
        kang_num = pd.to_numeric(df["kanguchi"], errors="coerce")
        # 欠損は許容、2m以下の数値のみ除外
        df = df[~((kang_num.notna()) & (kang_num <= 2.0))].copy()
    # 取引時点を date 化
    df["transaction_date"] = df["transaction_quarter_str"].apply(_parse_quarter)
    df = df[df["transaction_date"].notna()]
    # 派生列：log(unit_price), log(area)
    df["ln_unit_price"] = df["unit_price"].apply(math.log)
    df["ln_area"] = df["area"].apply(math.log)
    return df.reset_index(drop=True)


# 公示地価GeoJSON（国土数値情報 L01）の市区町村名短縮形 → 完全形マッピング
KOJI_CITY_NORMALIZE = {
    # 東京23区
    "千代田": "千代田区", "中央": "中央区", "港": "港区",
    "新宿": "新宿区", "文京": "文京区", "台東": "台東区",
    "墨田": "墨田区", "江東": "江東区", "品川": "品川区",
    "目黒": "目黒区", "大田": "大田区", "世田谷": "世田谷区",
    "渋谷": "渋谷区", "中野": "中野区", "杉並": "杉並区",
    "豊島": "豊島区", "北": "北区", "荒川": "荒川区",
    "板橋": "板橋区", "練馬": "練馬区", "足立": "足立区",
    "葛飾": "葛飾区", "江戸川": "江戸川区",
    # 主要市
    "八王子": "八王子市", "立川": "立川市", "武蔵野": "武蔵野市",
    "三鷹": "三鷹市", "青梅": "青梅市", "府中": "府中市",
    "昭島": "昭島市", "調布": "調布市", "町田": "町田市",
    "小金井": "小金井市", "小平": "小平市", "日野": "日野市",
    "東村山": "東村山市", "国分寺": "国分寺市", "国立": "国立市",
    "福生": "福生市", "狛江": "狛江市", "東大和": "東大和市",
    "清瀬": "清瀬市", "東久留米": "東久留米市", "武蔵村山": "武蔵村山市",
    "多摩": "多摩市", "稲城": "稲城市", "羽村": "羽村市",
    "あきる野": "あきる野市", "西東京": "西東京市",
}


def _normalize_koji_city(short_name: str) -> str:
    """公示地価GeoJSONの短縮形（"世田谷"）を MLIT 形式（"世田谷区"）に正規化。"""
    if not short_name:
        return ""
    if short_name in KOJI_CITY_NORMALIZE:
        return KOJI_CITY_NORMALIZE[short_name]
    # マッピング外は「○○区」をデフォルトで付与（東京23区想定）
    if short_name.endswith(("区", "市", "町", "村")):
        return short_name
    return short_name + "区"


def _extract_district_from_addr(addr: str, city: str) -> str:
    """住所文字列から町丁目部分を抽出。
    例: "東京都　世田谷区桜上水５丁目４８０番１２" → "桜上水"
    """
    if not addr:
        return ""
    s = str(addr).replace("　", "").replace("東京都", "").strip()
    s = s.replace(city, "", 1)
    # 漢数字・数字以降を除去（「桜上水５丁目...」→ 「桜上水」）
    m = re.match(r"([^０-９0-9一二三四五六七八九十]+)", s)
    return m.group(1).strip() if m else s


def load_koji_geojson(path, recent_years: int = 5) -> pd.DataFrame:
    """国土数値情報 L01（地価公示）GeoJSON を読み込み、過去 recent_years 年分の年次価格を
    展開した DataFrame を返す。既存 load_koji_csv と同形式。

    年マッピング: L01_007=最新年、L01_105=同年価格、L01_104=前年、L01_103=前々年、...
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    rows = []
    for feat in data.get("features", []):
        p = feat.get("properties", {})
        city_short = str(p.get("L01_024", "") or "")
        if not city_short:
            continue
        city = _normalize_koji_city(city_short)
        addr = str(p.get("L01_025", "") or "")
        district = _extract_district_from_addr(addr, city)
        try:
            ref_year = int(p.get("L01_007"))
        except (TypeError, ValueError):
            continue
        std_id = "-".join(str(p.get(f"L01_{i:03d}", "")) for i in (1, 2, 3))
        # 公示地価地点の追加属性（概要表示用）
        def _safe(field, default=""):
            v = p.get(field)
            if v in (None, "", "_"):
                return default
            return v
        attrs = {
            "address": str(_safe("L01_025", "")),
            "area_sqm": _safe("L01_027", None),  # 地積
            "use_detail": str(_safe("L01_029", "")),  # 利用区分
            "frontage_ratio": _safe("L01_036", None),  # 間口比率
            "depth_ratio": _safe("L01_037", None),  # 奥行比率
            "road_type": str(_safe("L01_040", "")),  # 前面道路区分
            "road_dir": str(_safe("L01_041", "")),  # 前面道路方位
            "road_width": _safe("L01_042", None),  # 前面道路幅員
            "station": str(_safe("L01_048", "")),  # 最寄駅名
            "station_dist_m": _safe("L01_050", None),  # 駅距離(m)
            "zoning": str(_safe("L01_051", "")),  # 用途地域
            "building_coverage": _safe("L01_057", None),  # 建ぺい率
            "floor_area_ratio": _safe("L01_058", None),  # 容積率
        }
        # L01_105 が ref_year 価格、L01_104 が ref_year-1, ...
        for i in range(recent_years):
            field = f"L01_{105-i:03d}"
            year = ref_year - i
            v = p.get(field)
            try:
                price = float(v) if v not in (None, "", "_") else None
            except (TypeError, ValueError):
                price = None
            if price and price > 0:
                row = {
                    "標準地番号": std_id,
                    "prefecture": "東京都",
                    "city": city,
                    "district": district,
                    "price_date": date(year, 1, 1),
                    "price_per_sqm": price,
                    "use": p.get("L01_028", ""),
                }
                row.update(attrs)
                rows.append(row)
    return pd.DataFrame(rows).reset_index(drop=True)


def load_koji_auto(path) -> pd.DataFrame:
    """ファイル拡張子で CSV/GeoJSON を自動判定して読み込む。"""
    p = str(path).lower()
    if p.endswith(".geojson") or p.endswith(".json"):
        return load_koji_geojson(path)
    return load_koji_csv(path)


def load_kijun_auto(path) -> pd.DataFrame:
    """基準地価ファイルの自動判定（GeoJSON/CSV）。Noneや空文字列の場合は空DataFrameを返す。"""
    if path is None or path == "" or not Path(path).exists():
        return pd.DataFrame(columns=["標準地番号", "prefecture", "city",
                                     "district", "price_date", "price_per_sqm"])
    p = str(path).lower()
    if p.endswith(".geojson") or p.endswith(".json"):
        return load_koji_geojson(path)  # 同じL01スキーマと仮定
    return load_kijun_csv(path)


def load_koji_csv(path) -> pd.DataFrame:
    """公示地価 CSV を読み込む。"""
    df = pd.read_csv(path, encoding="utf-8-sig")
    rename = {
        "都道府県名": "prefecture", "市区町村名": "city", "地区名": "district",
        "価格時点": "price_date", "価格(円/㎡)": "price_per_sqm",
    }
    df = df.rename(columns=rename)
    df["price_date"] = pd.to_datetime(df["price_date"]).dt.date
    df["price_per_sqm"] = df["price_per_sqm"].apply(_to_num)
    return df.dropna(subset=["price_per_sqm"]).reset_index(drop=True)


def load_kijun_csv(path) -> pd.DataFrame:
    """基準地価 CSV を読み込む。公示地価とほぼ同形式。"""
    df = pd.read_csv(path, encoding="utf-8-sig")
    rename = {
        "都道府県名": "prefecture", "市区町村名": "city", "地区名": "district",
        "価格時点": "price_date", "価格(円/㎡)": "price_per_sqm",
    }
    df = df.rename(columns=rename)
    df["price_date"] = pd.to_datetime(df["price_date"]).dt.date
    df["price_per_sqm"] = df["price_per_sqm"].apply(_to_num)
    return df.dropna(subset=["price_per_sqm"]).reset_index(drop=True)


if __name__ == "__main__":
    # 単独実行で動作確認
    here = Path(__file__).parent.parent / "samples"
    mlit = load_mlit_csv(here / "sample_mlit.csv")
    koji = load_koji_csv(here / "sample_koji.csv")
    kijun = load_kijun_csv(here / "sample_kijun.csv")
    print(f"MLIT: {len(mlit)} rows, columns={list(mlit.columns)}")
    print(mlit.head(3))
    print(f"KOJI: {len(koji)} rows")
    print(koji.head(3))
    print(f"KIJUN: {len(kijun)} rows")
