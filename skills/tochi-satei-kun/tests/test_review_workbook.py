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

"""確認用ワークブックと JSON の整合検証。

検証する内容:
- シート構成が 確認用 / グラフ の 2 枚であること（業者用・顧客用を生成しない）
- A1 の表示から「認証」が消えていること
- 確認用 xlsx と JSON が、採用単価・採用総額・採用件数・採用事例番号・価格レンジで
  一致すること（`money.round_money` を共通の整数化ルールとして通しているため）
- 同じ入力で再実行したとき、JSON がバイト単位で完全一致すること
"""
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

import pytest
from openpyxl import load_workbook

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from main import run_pipeline
from money import round_money

SAMPLES = ROOT / "samples"
ASOF = date(2026, 5, 1)


def _run(out_dir: Path):
    xlsx_path = run_pipeline(
        str(SAMPLES / "sample_property.json"),
        str(SAMPLES / "sample_mlit.csv"),
        str(SAMPLES / "sample_koji.csv"),
        None,
        out_dir=str(out_dir),
        asof=ASOF,
        json_out_path=str(out_dir / "result.json"),
    )
    result = json.loads((out_dir / "result.json").read_text(encoding="utf-8"))
    return xlsx_path, result


@pytest.fixture(scope="module")
def artifacts(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("review_workbook")
    xlsx_path, result = _run(out_dir)
    return load_workbook(xlsx_path), result, out_dir


def _sheet_text(ws):
    return "\n".join(
        str(c.value) for row in ws.iter_rows() for c in row if c.value is not None
    )


def _yen(text):
    """「3,624,618円」のような表示文字列から整数を取り出す。"""
    return int(re.sub(r"[^\d-]", "", text))


# ===== シート構成 =====
def test_sheet_names_are_kakunin_and_graph(artifacts):
    wb, _, _ = artifacts
    assert wb.sheetnames == ["確認用", "グラフ"]


def test_gyosha_sheet_is_not_generated(artifacts):
    wb, _, _ = artifacts
    assert "業者用" not in wb.sheetnames


def test_kokyaku_sheet_is_not_generated(artifacts):
    wb, _, _ = artifacts
    assert "顧客用" not in wb.sheetnames


def test_json_is_still_generated(artifacts):
    _, result, out_dir = artifacts
    assert (out_dir / "result.json").exists()
    assert result["schema_version"]
    assert result["engine"]["name"] == "tochi-satei-kun"
    assert result["assessment"]["adopted_unit_price"] is not None


# ===== A1 表示 =====
def test_a1_has_no_authentication_wording(artifacts):
    wb, _, _ = artifacts
    a1 = wb["確認用"]["A1"].value
    assert "認証" not in a1, f"A1 に『認証』が残っている: {a1}"
    assert a1.startswith("tochi-satei-kun v")
    assert a1.endswith("出力")


def test_workbook_has_no_authentication_wording_anywhere(artifacts):
    wb, _, _ = artifacts
    for name in wb.sheetnames:
        assert "認証" not in _sheet_text(wb[name]), f"{name} シートに『認証』が残っている"


# ===== 重要事項（顧客用シート廃止で失われていないこと） =====
def test_important_notes_survive_on_kakunin_sheet(artifacts):
    wb, _, _ = artifacts
    text = _sheet_text(wb["確認用"])
    assert "■ 重要事項（机上査定の前提と免責）" in text
    assert "不動産鑑定評価書ではなく" in text


# ===== xlsx と JSON の一致 =====
def test_adopted_unit_price_matches_between_xlsx_and_json(artifacts):
    wb, result, _ = artifacts
    xlsx_unit = _yen(wb["確認用"]["B21"].value)
    assert xlsx_unit == result["assessment"]["adopted_unit_price"]


def test_adopted_total_price_matches_between_xlsx_and_json(artifacts):
    wb, result, _ = artifacts
    xlsx_total = _yen(wb["確認用"]["C21"].value)
    assert xlsx_total == result["assessment"]["adopted_total_price"]


def test_adopted_unit_price_uses_shared_rounding_rule(artifacts):
    """1 円差の再発防止：表示値は round_money（四捨五入）以外の整数化を経ていない。

    採用単価と採用総額はどちらも丸める前の内部値から独立に整数化されるため、
    総額 == 丸めた単価 × 面積 とは限らない（面積 1 ㎡あたり最大 0.5 円のずれ）。
    ここで固定するのは「xlsx と JSON が同じ整数化ルールを通ること」。
    """
    wb, result, _ = artifacts
    unit = result["assessment"]["adopted_unit_price"]
    total = result["assessment"]["adopted_total_price"]
    area = result["subject"]["area_sqm"]

    assert _yen(wb["確認用"]["B21"].value) == round_money(unit)
    assert _yen(wb["確認用"]["C21"].value) == total
    # 総額と単価×面積の差は、単価側の丸め誤差（±0.5 円）× 面積に収まる
    assert abs(total - unit * area) <= area / 2 + 1


def test_case_count_matches_between_xlsx_and_json(artifacts):
    wb, result, _ = artifacts
    n_cases = result["assessment"]["n_cases"]
    assert n_cases == len(result["comparables"])
    text = _sheet_text(wb["確認用"])
    assert f"{n_cases} 件" in text or f"{n_cases}件" in text


def test_case_numbers_match_between_xlsx_and_json(artifacts):
    wb, result, _ = artifacts
    json_case_nos = {c["case_no"] for c in result["comparables"]}
    text = _sheet_text(wb["確認用"])
    # 比準表は「事例番号」列に case_no を整数で並べる。順序ではなく集合で照合する。
    xlsx_case_nos = {int(m) for m in re.findall(r"事例(\d+)", text)}
    if not xlsx_case_nos:
        xlsx_case_nos = {
            c.value for row in wb["確認用"].iter_rows() for c in row
            if isinstance(c.value, int) and c.value in json_case_nos
        }
    assert json_case_nos <= xlsx_case_nos, (
        f"JSON の採用事例 {json_case_nos} が確認用シートに揃っていない: {xlsx_case_nos}"
    )


def test_price_range_matches_between_xlsx_and_json(artifacts):
    """価格レンジは確認用シートでは上位3桁丸め表示。丸める前の値としては JSON と一致する。"""
    wb, result, _ = artifacts
    sys.path.insert(0, str(ROOT / "scripts"))
    from xlsx_common import _round_3sig

    rng = result["assessment"]["price_range"]
    text = _sheet_text(wb["確認用"])
    for key in ("high_total_price", "central_total_price", "low_total_price"):
        expected = f"{_round_3sig(rng[key]):,}円"
        assert expected in text, f"{key} の表示 {expected} が確認用シートに無い"


# ===== 再現性 =====
def test_same_input_produces_identical_json_bytes(tmp_path):
    first_dir = tmp_path / "run1"
    second_dir = tmp_path / "run2"
    first_dir.mkdir()
    second_dir.mkdir()
    _run(first_dir)
    _run(second_dir)
    first = (first_dir / "result.json").read_bytes()
    second = (second_dir / "result.json").read_bytes()
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest(), (
        "同じ入力なのに JSON のバイト列が一致しない（SHA-256 比較が使えない）"
    )


def test_same_input_produces_identical_key_results(tmp_path):
    first_dir = tmp_path / "run1"
    second_dir = tmp_path / "run2"
    first_dir.mkdir()
    second_dir.mkdir()
    _, first = _run(first_dir)
    _, second = _run(second_dir)
    assert first["assessment"] == second["assessment"]
    assert [c["case_no"] for c in first["comparables"]] == \
           [c["case_no"] for c in second["comparables"]]
    assert first["warnings"] == second["warnings"]


# ===== 丸めルールそのもの =====
def test_round_money_is_half_up_not_bankers_rounding():
    assert round_money(0.5) == 1
    assert round_money(1.5) == 2
    assert round_money(2.5) == 3
    assert round_money(-0.5) == -1
    assert round_money(3_624_617.6) == 3_624_618
    assert round_money(None) is None
    assert round_money(float("nan")) is None
