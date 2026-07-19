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

"""分割：顧客用シート描画（v1.2.7、Cowork 読み込み対策）"""
from xlsx_common import *


def _qualitative(beta_label, target_v, mean_v):
    """個別要因の定性表現（係数を開示せず方向と程度のみ）。"""
    if mean_v == 0 or mean_v is None or target_v is None:
        return None
    diff = target_v - mean_v
    if abs(diff) < 0.1 * abs(mean_v):
        return "同水準"
    if diff > 0:
        return "やや広め" if "面積" in beta_label else "やや遠め" if "駅" in beta_label else "ややプラス要因"
    return "やや狭め" if "面積" in beta_label else "やや近め" if "駅" in beta_label else "ややマイナス要因"


def _write_kokyaku_sheet(wb: Workbook, ctx: dict):
    ws = wb.create_sheet("顧客用")
    # 列幅を冒頭で設定（Cowork 配布層 truncate 対策。末尾の再設定もそのまま残す）
    _adjust_col_widths(ws, [12, 26, 16, 18, 14, 14])
    target = ctx["target"]
    asof = ctx["asof"]
    rate_info = ctx["rate_info"]
    cases = ctx["cases"]
    assess = ctx["assess"]
    standard_check = ctx["standard_check"]
    is_degraded = not ctx["hedonic"]["ok"]
    hijun_rows = ctx.get("hijun_rows", [])

    # 印刷ヘッダ・フッタは _apply_page_setup() で統一設定（OEM 想定でブランド名は付けない）

    r = 1
    # タイトル（降格時はラベル変更）
    chome = target.get("丁目", "")
    location = f"{target['市区町村名']} {target.get('地区名', '')}{chome}"
    title_text = (
        f"土地価格 参考情報 — {location}"
        if is_degraded
        else f"土地机上査定書 — {location}"
    )
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
    assert_clean(title_text, "title")
    _set(ws, r, 1, title_text, font=TITLE_FONT, fill=TITLE_FILL,
         align=Alignment(horizontal="left", vertical="center"))
    ws.row_dimensions[r].height = 28
    r += 1

    # （OEM 想定のため自動生成バナーは出さない。提供者表示は印刷フッタや別途運用で）

    # 降格時の参考情報バナー（赤色）
    if is_degraded:
        warn_red_fill = PatternFill("solid", fgColor="C00000")
        warn_red_font = Font(name="游ゴシック", size=11, bold=True, color="FFFFFF")
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
        banner_text = (
            "※ 取引事例件数が不足しているため、本資料は「参考情報」としてご覧ください（机上査定書ではありません）。"
            " 正式な査定価格は、ご担当者による現地確認・追加調査を経て決定する必要があります。"
        )
        assert_clean(banner_text, "degraded banner")
        _set(ws, r, 1, banner_text, font=warn_red_font, fill=warn_red_fill,
             align=Alignment(wrap_text=True, vertical="center"))
        ws.row_dimensions[r].height = 38
        r += 2

    # ■ 査定結果サマリ
    _section_header(ws, r, "■ 査定結果サマリ", end_col=6)
    r += 1
    rng = assess["range"]
    target_area = target["面積(㎡)"]

    # 査定価格（総額＋㎡単価＋坪単価併記、降格時はラベル変更）
    price_label = "参考価格" if is_degraded else "査定価格"
    summary_rows = [
        (price_label, _format_price_full(rng["central_total"], target_area)),
        ("面積", f"{target_area} ㎡"),
        ("査定時点", asof.isoformat()),
    ]
    for label, value in summary_rows:
        assert_clean(label, "summary label")
        assert_clean(value, "summary value")
        _set(ws, r, 1, label, font=LABEL_FONT, border=True)
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=6)
        _set(ws, r, 2, value, font=VALUE_FONT, border=True)
        r += 1
    r += 1

    # 価格レンジ（上限／中央／下限）
    _section_header(ws, r, "■ 価格レンジ", end_col=6)
    r += 1
    for j, h in enumerate(["区分", "総額", "㎡単価", "坪単価"]):
        _set(ws, r, j+1, h, font=LABEL_FONT,
             fill=PatternFill("solid", fgColor="D9E1F2"), border=True)
    r += 1
    for label, total, unit in [
        ("上限", rng["high_total"], rng["high_unit"]),
        ("中央", rng["central_total"], rng["central_unit"]),
        ("下限", rng["low_total"], rng["low_unit"]),
    ]:
        total_r = _round_3sig(total) if total else None
        unit_sqm_r = _round_3sig(unit) if unit else None
        unit_tsubo_r = _round_3sig(unit / 0.3025) if unit else None
        _set(ws, r, 1, label, font=LABEL_FONT, border=True)
        _set(ws, r, 2, f"{total_r:,}円" if total_r else "", font=VALUE_FONT, border=True)
        _set(ws, r, 3, f"{unit_sqm_r:,}円" if unit_sqm_r else "", font=VALUE_FONT, border=True)
        _set(ws, r, 4, f"{unit_tsubo_r:,}円" if unit_tsubo_r else "", font=VALUE_FONT, border=True)
        r += 1
    r += 1

    # ■ 標準価格
    _section_header(ws, r, "■ 標準価格", end_col=6)
    r += 1
    if standard_check.get("standard_price_per_sqm"):
        label = standard_check.get("label", "")
        if label:
            text = (f"本地区の{standard_check['source']}による標準価格"
                    f"（{label}）は {int(standard_check['standard_price_per_sqm']):,} 円/㎡ です。")
        else:
            text = f"本地区の{standard_check['source']}による標準価格は {int(standard_check['standard_price_per_sqm']):,} 円/㎡ です。"
    else:
        text = "本地区の公的な標準価格データが取得できなかったため、参考情報なしで査定しています。"
    assert_clean(text, "standard")
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
    _set(ws, r, 1, text, font=VALUE_FONT, align=Alignment(wrap_text=True, vertical="top"))
    ws.row_dimensions[r].height = 30
    r += 2

    # ■ 時点修正
    _section_header(ws, r, "■ 時点修正", end_col=6)
    r += 1
    if rate_info.get("rate") is not None:
        rate_pct = rate_info["rate"] * 100
        direction = "上昇" if rate_pct > 0 else "下落" if rate_pct < 0 else "横ばい"
        text = (f"直近の本地区の地価は年率 {rate_pct:+.2f}% で{direction}しています。"
                f"この動きを踏まえて、過去の取引事例を査定時点に補正しています。")
    else:
        text = "時点修正の根拠となる地価データが取得できなかったため、補正なしで査定しています。"
    assert_clean(text, "time_adjust")
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
    _set(ws, r, 1, text, font=VALUE_FONT, align=Alignment(wrap_text=True, vertical="top"))
    ws.row_dimensions[r].height = 36
    r += 2

    # ■ 公示価格の詳細（顧客用：縦並びで読みやすく）
    koji_points_k = standard_check.get("selected_points", []) if standard_check else []
    if koji_points_k:
        pt0 = koji_points_k[0]
        _section_header(ws, r, "■ 公示価格の詳細", end_col=6)
        r += 1
        short_id_k = _short_koji_id(str(pt0.get("id", "")))
        short_addr_k = _short_koji_addr(str(pt0.get("address", "")),
                                         str(pt0.get("district", "")))
        shape_k = _koji_shape_label(pt0.get("frontage_ratio"), pt0.get("depth_ratio"))
        price_k = pt0.get("price_at_asof")
        # 整形した項目リスト
        koji_info_lines = [
            ("公示番号", short_id_k),
            ("公示価格", f"{int(price_k):,} 円/㎡" if price_k else "—"),
            ("所在", short_addr_k or "—"),
            ("最寄駅", f"{pt0.get('station','')} （{int(pt0.get('station_dist_m') or 0)} m）"
                if pt0.get("station") else "—"),
            ("前面道路", f"{pt0.get('road_type','')} 幅員{int(pt0.get('road_width') or 0)}m "
                f"{pt0.get('road_dir','')}向"
                if pt0.get("road_type") else "—"),
            ("形状", shape_k),
            ("地積", f"{int(pt0.get('area_sqm') or 0)} ㎡" if pt0.get("area_sqm") else "—"),
            ("用途地域", pt0.get("zoning", "") or "—"),
            ("容積率", f"{int(pt0.get('floor_area_ratio') or 0)}%"
                if pt0.get("floor_area_ratio") else "—"),
        ]
        koji_label_font = Font(name="ＭＳ Ｐゴシック", size=10, bold=True)
        koji_value_font = Font(name="ＭＳ Ｐゴシック", size=10)
        for lbl, val in koji_info_lines:
            assert_clean(lbl, "koji label")
            assert_clean(str(val), "koji value")
            _set(ws, r, 1, lbl, font=koji_label_font, border=True,
                 align=Alignment(horizontal="center", vertical="center"))
            ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=6)
            _set(ws, r, 2, str(val), font=koji_value_font, border=True,
                 align=Alignment(horizontal="left", vertical="center", wrap_text=True))
            r += 1
        # 注釈（簡潔に）
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
        _set(ws, r, 1,
             "※ 査定地と類似性の高い公示地です。",
             font=Font(name="ＭＳ Ｐゴシック", size=9, italic=True, color="595959"),
             align=Alignment(wrap_text=True, vertical="top"))
        ws.row_dimensions[r].height = 20
        r += 2

    # ■ 査定価格 / 参考価格
    section_label = "■ 参考価格" if is_degraded else "■ 机上査定価格"
    _section_header(ws, r, section_label, end_col=6)
    r += 1
    if is_degraded:
        text = (f"上記を踏まえた本物件の参考価格は {_format_price_full(rng['central_total'], target_area)} です。"
                f"（取引事例件数が不足しているため、正式な机上査定書ではありません）")
    else:
        text = f"上記を踏まえた本物件の机上査定価格は {_format_price_full(rng['central_total'], target_area)} となります。"
    assert_clean(text, "final")
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
    _set(ws, r, 1, text, font=BIG_VALUE_FONT, align=Alignment(wrap_text=True, vertical="center"))
    ws.row_dimensions[r].height = 50
    r += 1

    # 価格直下の短縮版ディスクレーマー（読まないユーザー対策・必須UX）
    short_disc = (
        f"※ 上記は {asof.isoformat()} 時点の机上査定（参考値）です。"
        "現地・役所・法務局調査未実施。成約価格・担保評価額・鑑定評価額とは異なる場合があります。"
        "第三者提示、金融機関提出、訴訟・税務用途には使用できません。"
    )
    assert_clean(short_disc, "short disclaimer")
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
    _set(ws, r, 1, short_disc,
         font=Font(name="游ゴシック", size=9, italic=True, color="C00000"),
         fill=PatternFill("solid", fgColor="FFF2CC"),
         align=Alignment(wrap_text=True, vertical="center"))
    ws.row_dimensions[r].height = 38
    r += 2

    # ■ 比準表（取引事例比較表による試算）— 松田テンプレート準拠
    if hijun_rows:
        _insert_page_break(ws, r)
        primary_h = next((h for h in hijun_rows if h.get("順位") == "規範性の高い事例"), hijun_rows[0])
        _section_header(ws, r, "■ 比準表（取引事例比較表による試算）", end_col=6)
        r += 1
        # テンプレートのフォント・書式
        TMPL_FONT = Font(name="ＭＳ Ｐゴシック", size=11)
        TMPL_FONT_BOLD = Font(name="ＭＳ Ｐゴシック", size=11, bold=True)
        TMPL_FONT_SHISAN = Font(name="ＭＳ Ｐゴシック", size=11, bold=True, color="C00000")
        ALIGN_CENTER = Alignment(horizontal="center", vertical="center")
        ALIGN_CENTER_H = Alignment(horizontal="center")
        NUM_FMT = "#,##0_);[Red](#,##0)"
        BORDER_FULL = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
        BORDER_TOP = Border(left=THIN, right=THIN, top=THIN)
        BORDER_BOT = Border(left=THIN, right=THIN, bottom=THIN)

        # 事例番号（1行、B-C 列）
        _set(ws, r, 2, "事例番号", font=TMPL_FONT_BOLD, border=BORDER_FULL, align=ALIGN_CENTER_H)
        _set(ws, r, 3, primary_h.get("事例番号", "?"),
             font=TMPL_FONT, border=BORDER_FULL, align=ALIGN_CENTER_H)
        r += 1

        # 取引価格（1行）
        _set(ws, r, 2, "取引価格（円/㎡）", font=TMPL_FONT_BOLD, border=BORDER_FULL, align=ALIGN_CENTER_H)
        price_cell = ws.cell(row=r, column=3, value=int(primary_h["取引価格"]))
        price_cell.font = TMPL_FONT
        price_cell.border = BORDER_FULL
        price_cell.alignment = ALIGN_CENTER_H
        price_cell.number_format = NUM_FMT
        price_row = r
        r += 1

        # 事情補正（2行、B列縦マージ、C列に分子/分母）
        ws.merge_cells(start_row=r, start_column=2, end_row=r+1, end_column=2)
        _set(ws, r, 2, "事情補正", font=TMPL_FONT_BOLD, border=BORDER_FULL, align=ALIGN_CENTER)
        jijo_apply = primary_h.get("事情補正_適用", False)
        jijo_num_val = round(primary_h["事情補正"] * 100, 1)
        if jijo_num_val == int(jijo_num_val):
            jijo_num_val = int(jijo_num_val)
        _set(ws, r, 3, jijo_num_val, font=TMPL_FONT, border=BORDER_TOP, align=ALIGN_CENTER_H)
        jijo_num_row = r
        r += 1
        _set(ws, r, 3, "―" if not jijo_apply else 100,
             font=TMPL_FONT, border=BORDER_BOT, align=ALIGN_CENTER_H)
        r += 1

        # 時点修正（2行）
        ws.merge_cells(start_row=r, start_column=2, end_row=r+1, end_column=2)
        _set(ws, r, 2, "時点修正", font=TMPL_FONT_BOLD, border=BORDER_FULL, align=ALIGN_CENTER)
        time_num_val = round(primary_h["時点修正"] * 100, 1)
        if time_num_val == int(time_num_val):
            time_num_val = int(time_num_val)
        _set(ws, r, 3, time_num_val, font=TMPL_FONT, border=BORDER_TOP, align=ALIGN_CENTER_H)
        time_num_row = r
        r += 1
        _set(ws, r, 3, 100, font=TMPL_FONT, border=BORDER_BOT, align=ALIGN_CENTER_H)
        r += 1

        # 形状補正（2行、100/分母 形式）
        ws.merge_cells(start_row=r, start_column=2, end_row=r+1, end_column=2)
        _set(ws, r, 2, "形状補正", font=TMPL_FONT_BOLD, border=BORDER_FULL, align=ALIGN_CENTER)
        shape_mult = float(primary_h["標準化補正"])
        # 案件評点（=mult*100）を分母に表示。倍率は 下/上 で計算
        shape_den_val = round(shape_mult * 100, 1) if shape_mult > 0 else 100
        if shape_den_val == int(shape_den_val):
            shape_den_val = int(shape_den_val)
        _set(ws, r, 3, 100, font=TMPL_FONT, border=BORDER_TOP, align=ALIGN_CENTER_H)
        shape_num_row = r
        r += 1
        _set(ws, r, 3, shape_den_val, font=TMPL_FONT, border=BORDER_BOT, align=ALIGN_CENTER_H)
        shape_den_row = r
        r += 1

        # 地域格差（2行、100/分母 形式）
        ws.merge_cells(start_row=r, start_column=2, end_row=r+1, end_column=2)
        _set(ws, r, 2, "地域格差", font=TMPL_FONT_BOLD, border=BORDER_FULL, align=ALIGN_CENTER)
        chi_mult = float(primary_h["地域格差"])
        # 相乗積と一致する案件評点（=mult*100）を分母に
        chi_den_val = round(chi_mult * 100, 1) if chi_mult > 0 else 100
        if chi_den_val == int(chi_den_val):
            chi_den_val = int(chi_den_val)
        _set(ws, r, 3, 100, font=TMPL_FONT, border=BORDER_TOP, align=ALIGN_CENTER_H)
        chi_num_row = r
        r += 1
        _set(ws, r, 3, chi_den_val, font=TMPL_FONT, border=BORDER_BOT, align=ALIGN_CENTER_H)
        chi_den_row = r
        r += 1

        # 標準画地の試算値（Excel関数式、2行マージ）
        ws.merge_cells(start_row=r, start_column=2, end_row=r+1, end_column=2)
        ws.merge_cells(start_row=r, start_column=3, end_row=r+1, end_column=3)
        _set(ws, r, 2, "標準画地の試算値",
             font=TMPL_FONT_BOLD, border=BORDER_FULL, align=ALIGN_CENTER)
        # v1.2.3: 標準化補正・地域格差は「上=100, 下=案件評点」配置 → 補正率 = 100/案件評点
        # 即ち expr では num/den（上/下）で割る形にする
        expr = (f"C{price_row}*C{jijo_num_row}/100*C{time_num_row}/100"
                f"*C{shape_num_row}/C{shape_den_row}*C{chi_num_row}/C{chi_den_row}")
        formula = f"=ROUND({expr},-(LEN(INT({expr}))-3))"
        formula_cell = ws.cell(row=r, column=3, value=formula)
        formula_cell.font = TMPL_FONT_SHISAN
        formula_cell.border = BORDER_FULL
        formula_cell.alignment = ALIGN_CENTER
        formula_cell.number_format = NUM_FMT
        shisan_row = r  # 標準画地の試算値 行（査定価格formula参照用）
        r += 2

        # ■ 個別格差（ヘドニック補正に反映済みの説明表示。価格へ再適用しない）
        # 添付参考のように、ラベルと数値を「青字」で表示して標準化補正と差別化
        BLUE_LABEL_FONT = Font(name="ＭＳ Ｐゴシック", size=11, color="2F5496")
        BLUE_VALUE_FONT = Font(name="ＭＳ Ｐゴシック", size=11, color="2F5496")
        SECTION_BLUE_FONT = Font(name="ＭＳ Ｐゴシック", size=11, bold=True, color="FFFFFF")
        SECTION_BLUE_FILL = PatternFill("solid", fgColor="2F5496")

        # 標準画地の試算値の下に縦並びで表示（B-C 列にセクションヘッダ）
        _set(ws, r, 2, "■ 個別格差",
             font=SECTION_BLUE_FONT, fill=SECTION_BLUE_FILL,
             border=BORDER_FULL, align=ALIGN_CENTER)
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=3)
        r += 1

        def _fmt_kobetsu(v):
            """個別格差値の表示用整形（整数化、±0は0）"""
            iv = round(v, 1)
            return int(iv) if iv == int(iv) else iv

        # v1.2.1: target が中間画地（角地補正率(%)未入力 or 0）の場合は角地行を非表示
        target_kado_val = primary_h.get("個別格差_角地", 0)
        kado_row = None
        if abs(round(target_kado_val, 1)) >= 0.05:
            _set(ws, r, 2, "角地（角地）", font=BLUE_LABEL_FONT, border=BORDER_FULL, align=ALIGN_CENTER_H)
            _set(ws, r, 3, _fmt_kobetsu(target_kado_val),
                 font=BLUE_VALUE_FONT, border=BORDER_FULL, align=ALIGN_CENTER_H)
            kado_row = r
            r += 1

        # 方位（青字、target の方位をラベルに）
        target_dir = str(target.get("前面道路:方位", "")).strip()
        houi_label = f"方位（{target_dir}）" if target_dir else "方位"
        _set(ws, r, 2, houi_label, font=BLUE_LABEL_FONT, border=BORDER_FULL, align=ALIGN_CENTER_H)
        houi_val = _fmt_kobetsu(primary_h.get("個別格差_方位", 0))
        _set(ws, r, 3, houi_val, font=BLUE_VALUE_FONT, border=BORDER_FULL, align=ALIGN_CENTER_H)
        houi_row = r
        r += 1

        # 不整形（青字、v1.2.1: target の土地形状をラベルに）
        target_shape = str(target.get("土地の形状", "")).strip()
        fusei_label = f"不整形（{target_shape}）" if target_shape else "不整形"
        _set(ws, r, 2, fusei_label, font=BLUE_LABEL_FONT, border=BORDER_FULL, align=ALIGN_CENTER_H)
        fusei_val = _fmt_kobetsu(primary_h.get("個別格差_不整形", 0))
        _set(ws, r, 3, fusei_val, font=BLUE_VALUE_FONT, border=BORDER_FULL, align=ALIGN_CENTER_H)
        fusei_row = r
        r += 1

        # 総和（Excel関数式、黒字）— 表示中の格差行のみを積算
        _set(ws, r, 2, "総和", font=TMPL_FONT_BOLD, border=BORDER_FULL, align=ALIGN_CENTER_H)
        factor_refs_k = []
        if kado_row is not None:
            factor_refs_k.append(f"(100+C{kado_row})/100")
        factor_refs_k.append(f"(100+C{houi_row})/100")
        factor_refs_k.append(f"(100+C{fusei_row})/100")
        soan_formula = "=" + "*".join(factor_refs_k) + "*100"
        soan_cell = ws.cell(row=r, column=3, value=soan_formula)
        soan_cell.font = TMPL_FONT
        soan_cell.border = BORDER_FULL
        soan_cell.alignment = ALIGN_CENTER_H
        soan_cell.number_format = "0.00"
        soan_row = r
        r += 2  # 1行空ける

        # 案件査定価格（ラベル青字、値は赤字）
        BLUE_BOLD_LABEL = Font(name="ＭＳ Ｐゴシック", size=11, bold=True, color="2F5496")
        _set(ws, r, 2, "案件査定価格（円/㎡）",
             font=BLUE_BOLD_LABEL, border=BORDER_FULL, align=ALIGN_CENTER_H)
        anken_inner_k = f"C{shisan_row}*C{soan_row}"
        anken_formula = f"=ROUND({anken_inner_k},-(LEN(INT({anken_inner_k}))-3))/100"
        anken_cell = ws.cell(row=r, column=3, value=anken_formula)
        anken_cell.font = TMPL_FONT_SHISAN  # red bold
        anken_cell.border = BORDER_FULL
        anken_cell.alignment = ALIGN_CENTER_H
        anken_cell.number_format = NUM_FMT
        r += 2

        # 注釈
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
        _set(ws, r, 1,
             "※ 「事情補正」は売主・買主の事情が取引価格に影響している場合の調整、"
             "「時点修正」は取引時期と査定時点の地価変動による調整、"
             "「形状補正」「地域格差」はそれぞれ事例地と本物件の形状・地域条件の差を反映しています。"
             "角地・方位・不整形のうち価格に反映する補正は正本補正後単価へ一度だけ含め、"
             "同じ補正を重ねて乗じないようにしています。",
             font=Font(name="ＭＳ Ｐゴシック", size=9, italic=True, color="595959"),
             align=Alignment(wrap_text=True, vertical="top"))
        ws.row_dimensions[r].height = 40
        r += 2

    # ■ 査定の考え方
    _section_header(ws, r, "■ 査定の考え方", end_col=6)
    r += 1
    sentences = [
        "本査定は、本地区とその周辺で本物件と規範性の高い取引事例を複数選定し、",
        "それぞれの単価を本物件の特徴（面積・最寄駅までの距離・形状・接道など）に合わせて調整したうえで、査定価格を算出しています。",
        "なお、最も規範性の高い1件を「規範性の高い取引事例」として表示しています。",
        "標準価格や地価の動きとの整合も確認しています。",
        "あくまで一次査定であり、現地確認や市場動向によって最終価格は変動し得ます。",
    ]
    text = "".join(sentences)
    assert_clean(text, "story")
    ws.merge_cells(start_row=r, start_column=1, end_row=r+2, end_column=6)
    _set(ws, r, 1, text, font=VALUE_FONT, align=Alignment(wrap_text=True, vertical="top"))
    ws.row_dimensions[r].height = 80
    r += 4

    # ■ 重要事項（机上査定の前提と免責）
    _insert_page_break(ws, r)
    _section_header(ws, r, "■ 重要事項（机上査定の前提と免責）", end_col=6)
    r += 1

    # 1) 自動生成・鑑定評価書ではない
    text_1 = (
        "本書はご入力いただいた情報および国土交通省「不動産取引価格情報」「地価公示」等の"
        "公開データに基づき、ソフトウェアにより自動生成した机上査定です。"
        "本査定額は自動算出によるものであり、不動産鑑定評価基準に基づく不動産鑑定評価書ではなく、"
        "個別の不動産鑑定士による判断を経たものでもありません。"
    )
    assert_clean(text_1, "important note 1")
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
    _set(ws, r, 1, text_1, font=VALUE_FONT,
         align=Alignment(wrap_text=True, vertical="top"))
    ws.row_dimensions[r].height = 70
    r += 1

    # 2) 行っていない調査
    label_b = Font(name="游ゴシック", size=10, bold=True)
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
    _set(ws, r, 1, "本査定では、以下の調査を行っておりません。", font=label_b)
    r += 1
    skipped_surveys = [
        "対象不動産の現地調査（外観・内部・接道・近隣環境・越境・境界等）",
        "役所調査（公法上の規制、道路種別、インフラ、開発許可、建築確認履歴等）",
        "法務局調査（登記・公図・地積測量図・権利関係の精査）",
        "賃貸借契約・修繕履歴・個別契約条件の精査",
        "土壌汚染・地下埋設物・アスベスト等の物的リスク調査",
    ]
    for s in skipped_surveys:
        assert_clean(s, "skipped survey")
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
        _set(ws, r, 1, f"　・{s}", font=VALUE_FONT)
        r += 1
    r += 1

    # 3) 参考価格としての位置づけ
    text_3 = (
        "本査定額は、入力情報の正確性および公開情報の精度に依存する参考価格であり、"
        "実際の成約価格、金融機関の担保評価額、税務評価額、不動産鑑定評価額とは異なる場合があります。"
        "個別の減価要因（境界未確定、越境、再建築不可、心理的瑕疵、土壌汚染等）が存在する場合、"
        "査定額は大きく変動します。"
    )
    assert_clean(text_3, "important note 3")
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
    _set(ws, r, 1, text_3, font=VALUE_FONT,
         align=Alignment(wrap_text=True, vertical="top"))
    ws.row_dimensions[r].height = 60
    r += 1

    # 4) 利用範囲制限
    text_4 = (
        "本書は、利用者様ご自身の検討用途にのみご利用いただくものとし、"
        "第三者への提示・交付、訴訟・調停等の証拠資料、金融機関への提出資料、税務申告等の用途には使用できません。"
        "これらの用途には、不動産鑑定士による鑑定評価書の取得を推奨いたします。"
        "なお、本ツールの開発者が不動産鑑定士の資格を有していても、本書の出力が不動産鑑定評価であることを意味しません。"
    )
    assert_clean(text_4, "important note 4")
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
    _set(ws, r, 1, text_4, font=VALUE_FONT,
         align=Alignment(wrap_text=True, vertical="top"))
    ws.row_dimensions[r].height = 50
    r += 1

    # 5) 損害免責
    text_5 = (
        "本書の利用に起因して利用者様または第三者に生じた損害について、"
        "本ソフトウェア提供元およびその運営者は一切の責任を負いません。"
        "詳細は別途定める利用規約をご確認ください。"
    )
    assert_clean(text_5, "important note 5")
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
    _set(ws, r, 1, text_5, font=VALUE_FONT,
         align=Alignment(wrap_text=True, vertical="top"))
    ws.row_dimensions[r].height = 40
    r += 2

    # 価格時点を末尾で再表示（査定額と同じ視認性で）
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
    _set(ws, r, 1, f"価格時点：{asof.isoformat()}",
         font=Font(name="游ゴシック", size=12, bold=True),
         align=Alignment(horizontal="right"))
    r += 1

    _adjust_col_widths(ws, [12, 26, 16, 18, 14, 14])


