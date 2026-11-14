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

"""xlsx 生成のオーケストレータ（v1.2.7 で分割：xlsx_common / xlsx_kakunin_sheet）。

write_xlsx() がエントリポイント。各シート描画は専用モジュールに委譲。

シート構成：
- 確認用：n, R², 全β、補正内訳、参考値、警告、重要事項（机上査定の前提と免責）
- グラフ：価格推移・β棒グラフ・散布図

業者用 / 顧客用 の 2 シートを 確認用 1 枚へ統合した。人が入力・採用事例・
警告・計算結果を確認するためのシートという位置づけを 1 枚に集約している。
"""
from pathlib import Path

from openpyxl import Workbook

from xlsx_common import *
from xlsx_kakunin_sheet import _write_kakunin_sheet
from version import ENGINE_VERSION


def _apply_page_setup(wb: Workbook, target: dict):
    """各シートに印刷設定を適用。
    確認用: A3 横 + 縮小印刷（fitToWidth=1）
    グラフ: A4 横 + 縮小印刷（fitToPage）
    """
    from openpyxl.worksheet.page import PageMargins
    # PAPERSIZE: A3=8, A4=9
    A3_SIZE, A4_SIZE = 8, 9
    target_label = target.get("物件略号", "")

    # 確認用：A3 横、幅に合わせて縮小、印刷タイトルとして 1行目を固定
    if "確認用" in wb.sheetnames:
        ws = wb["確認用"]
        ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
        ws.page_setup.paperSize = A3_SIZE
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0  # 縦は複数ページ可
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.print_options.horizontalCentered = True
        ws.page_margins = PageMargins(left=0.4, right=0.4, top=0.6, bottom=0.6,
                                       header=0.3, footer=0.3)
        ws.print_title_rows = "1:1"
        ws.oddHeader.left.text = f"確認用 — {target_label}"
        ws.oddHeader.right.text = "&D"
        ws.oddFooter.center.text = "&P / &N"
        ws.sheet_view.view = "pageBreakPreview"

    # グラフ：A4 横、ページに合わせて縮小
    if "グラフ" in wb.sheetnames:
        gs = wb["グラフ"]
        gs.page_setup.orientation = gs.ORIENTATION_LANDSCAPE
        gs.page_setup.paperSize = A4_SIZE
        gs.page_setup.fitToWidth = 1
        gs.page_setup.fitToHeight = 1
        gs.sheet_properties.pageSetUpPr.fitToPage = True
        gs.print_options.horizontalCentered = True
        gs.page_margins = PageMargins(left=0.5, right=0.5, top=0.6, bottom=0.6)
        gs.oddHeader.left.text = f"附属資料 — {target_label}"
        gs.oddFooter.center.text = "&P / &N"
        gs.sheet_view.view = "pageBreakPreview"


def write_xlsx(ctx: dict, output_path: Path) -> Path:
    wb = Workbook()
    # Workbook プロパティにツール名とバージョンを記録（Excel「ファイル → 情報 → プロパティ」
    # で確認可能）。どのツールのどのバージョンで作成された出力かを確認するための表示。
    wb.properties.creator = f"tochi-satei-kun v{ENGINE_VERSION}"
    wb.properties.description = (
        "土地価格査定クン (tochi-satei-kun) — Apache License 2.0 OSS AVM. "
        "https://github.com/signal-yield/tochi-satei-kun"
    )
    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]
    _write_kakunin_sheet(wb, ctx)
    _apply_page_setup(wb, ctx.get("target", {}))
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    return output_path
