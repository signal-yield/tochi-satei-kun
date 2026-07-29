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

"""ダミーサンプル生成（実MLIT CSV受領前の暫定）。
実データ受領後はこのスクリプトを廃棄、または列名整合のリファレンスとして残す。
東京都港区の宅地(土地)を想定して合理的な分布で30件生成。
"""
import csv
import json
import math
import random
from pathlib import Path

random.seed(42)
HERE = Path(__file__).parent

DISTRICTS = ["麻布十番", "赤坂", "青山", "三田", "芝", "高輪", "白金", "六本木"]
STATIONS = {
    "麻布十番": "麻布十番", "赤坂": "赤坂", "青山": "表参道",
    "三田": "三田", "芝": "芝公園", "高輪": "高輪台",
    "白金": "白金台", "六本木": "六本木",
}
SHAPES = ["整形", "不整形", "袋地"]
SHAPE_W = [0.70, 0.20, 0.10]
ROAD_TYPES = ["区道", "都道", "私道"]  # MLIT実分類に整合
ROAD_W = [0.75, 0.10, 0.15]
ROAD_DIRS = ["北", "東", "南", "西", "北東", "南東", "南西", "北西"]
QUARTERS = [(2025, 3), (2025, 4), (2026, 1)]  # asof 2026-05-01 から見て直近1年内


SOUTH_DIRS = {"南", "南東", "南西"}


PRIVATE_ROAD = "私道"


def gen_unit_price(area, walk_min, shape, road_type, road_dir, kanguchi, road_width):
    """log-linear モデルで単価を生成（テスト時の符号判定の真値となる）。
    被説明変数: ln(単価/㎡)
      面積大→単価減（不動産通則）
      駅遠い→単価減
      不整形/袋地→単価減
      私道→単価減
      南向き→単価増
      間口広い→単価増
      道路幅員広い→単価増
    """
    base = math.log(4_000_000)  # 港区の標準単価400万/㎡
    eff = (
        -0.10 * (math.log(area) - math.log(100))
        - 0.03 * walk_min
        + 0.05 * (math.log(kanguchi) - math.log(6.0))
        + 0.04 * (math.log(road_width) - math.log(5.0))
        + (0.06 if road_dir in SOUTH_DIRS else 0.0)
        - (0.10 if shape == "不整形" else 0.0)
        - (0.25 if shape == "袋地" else 0.0)
        - 0.08 * (1 if road_type == PRIVATE_ROAD else 0)
        + random.gauss(0, 0.08)
    )
    return int(math.exp(base + eff))


def gen_mlit():
    rows = []
    for i in range(60):  # 直近1年フィルタ後でも30件以上残るよう増やす
        district = random.choice(DISTRICTS)
        area = round(random.uniform(50, 300), 0)
        walk = random.randint(3, 15)
        shape = random.choices(SHAPES, weights=SHAPE_W)[0]
        road_type = random.choices(ROAD_TYPES, weights=ROAD_W)[0]
        road_width = round(random.uniform(4.0, 10.0), 1)
        road_dir = random.choice(ROAD_DIRS)
        year, quarter = random.choice(QUARTERS)
        kanguchi = round(random.uniform(4.0, 15.0), 1)
        unit_price = gen_unit_price(area, walk, shape, road_type, road_dir, kanguchi, road_width)
        total_price = int(unit_price * area)
        # 取引価格は通常100万円単位丸め
        total_price = (total_price // 1_000_000) * 1_000_000

        row = {
            "種類": "宅地(土地)",
            "地域": "住宅地",
            "市区町村コード": "13103",
            "都道府県名": "東京都",
            "市区町村名": "港区",
            "地区名": district,
            "最寄駅:名称": STATIONS[district],
            "最寄駅:距離(分)": walk,
            "取引価格(総額)": total_price,
            "坪単価": "",
            "間取り": "",
            "面積(㎡)": int(area),
            "取引価格(㎡単価)": int(total_price / area),
            "土地の形状": shape,
            "間口": kanguchi,
            "延床面積(㎡)": "",
            "建築年": "",
            "建物の構造": "",
            "用途": "住宅",
            "今後の利用目的": "住宅",
            "前面道路:方位": road_dir,
            "前面道路:種類": road_type,
            "前面道路:幅員(m)": road_width,
            "都市計画": "第一種中高層住居専用地域",
            "建ぺい率(%)": 60,
            "容積率(%)": 200,
            "取引時点": f"{year}年第{quarter}四半期",
            "改装": "",
            "取引の事情等": "",
        }
        rows.append(row)
    return rows


def gen_koji():
    """公示地価（毎年1月1日時点）。同地区で過去3年分。"""
    base_unit_2023 = {"麻布十番": 4_500_000, "赤坂": 4_200_000, "白金": 3_800_000}
    rows = []
    for district, base in base_unit_2023.items():
        for year, growth in [(2023, 1.00), (2024, 1.04), (2025, 1.07)]:
            rows.append({
                "標準地番号": f"港-{district}-1",
                "都道府県名": "東京都",
                "市区町村名": "港区",
                "地区名": district,
                "価格時点": f"{year}-01-01",
                "価格(円/㎡)": int(base * growth),
                "用途": "住宅",
            })
    return rows


def gen_kijun():
    """基準地価（毎年7月1日時点）。同地区で過去3年分。"""
    base_unit_2023 = {"高輪": 3_900_000, "三田": 4_000_000}
    rows = []
    for district, base in base_unit_2023.items():
        for year, growth in [(2023, 1.00), (2024, 1.05), (2025, 1.08)]:
            rows.append({
                "基準地番号": f"港-{district}-1",
                "都道府県名": "東京都",
                "市区町村名": "港区",
                "地区名": district,
                "価格時点": f"{year}-07-01",
                "価格(円/㎡)": int(base * growth),
                "用途": "住宅",
            })
    return rows


def gen_property():
    """査定対象物件サンプル。"""
    return {
        "物件略号": "MIN001",
        "都道府県名": "東京都",
        "市区町村名": "港区",
        "地区名": "麻布十番",
        "面積(㎡)": 120,
        "最寄駅:名称": "麻布十番",
        "最寄駅:距離(分)": 7,
        "土地の形状": "整形",
        "間口": 8.0,
        "前面道路:方位": "南",
        "前面道路:種類": "公道",
        "前面道路:幅員(m)": 6.0,
        "都市計画": "第一種中高層住居専用地域",
        "建ぺい率(%)": 60,
        "容積率(%)": 200,
        "査定時点": "2026-05-01",
    }


def write_csv(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    write_csv(HERE / "sample_mlit.csv", gen_mlit())
    write_csv(HERE / "sample_koji.csv", gen_koji())
    write_csv(HERE / "sample_kijun.csv", gen_kijun())
    with open(HERE / "sample_property.json", "w", encoding="utf-8") as f:
        json.dump(gen_property(), f, ensure_ascii=False, indent=2)
    print("Generated sample_mlit.csv (60 rows), sample_koji.csv, sample_kijun.csv, sample_property.json")
