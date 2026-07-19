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

"""パイプライン全体のオーケストレータ。Claude が SKILL.md の指示でこれを呼ぶ。

v1.2.9 で、koji/kijun の標準価格計算・公示番号変換等の補助関数群を
`main_helpers.py` に分離し、本ファイルを 20KB 未満に圧縮。Cowork の
プラグイン配布層によるファイル truncate を回避するため。

使い方:
    python main.py <property.json> <mlit.csv> <koji.csv> <kijun.csv> [--out <dir>] [--asof YYYY-MM-DD]
"""
import argparse
import json
import math as _m
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from load_mlit import load_mlit_csv, load_koji_auto, load_kijun_auto
from scope import scope_dataframe, filter_recent_for_comparison, DEFAULT_COMPARISON_MONTHS
from similarity import compute_similarity, top_k
from time_adjust import annual_rate_for_city, apply_time_adjustment
from hedonic import fit_hedonic, annotate_district_mean, annotate_station_mean, DIR_SCORE
from correction import (apply_correction, correction_breakdown, hijun_correction_for_case,
                        compute_target_district_mean, compute_target_station_mean)
from hijun_breakdown import hijun_breakdown_detail  # v1.2.9: correction.py から分離
from aggregation import assess
from xlsx_writer import write_xlsx

# v1.2.9: 補助関数を main_helpers に分離
from main_helpers import (
    _hedonic_population_predict,
    _standard_price_for_city,
    _compute_koji_timeseries,
)


def run_pipeline(property_path: str, mlit_path: str, koji_path: str, kijun_path: str,
                 out_dir: str = None, asof: date = None) -> Path:
    # 1. 入力読込
    with open(property_path, encoding="utf-8") as f:
        target = json.load(f)
    if asof is None:
        asof_str = target.get("査定時点")
        if asof_str:
            asof = datetime.strptime(asof_str, "%Y-%m-%d").date()
        else:
            asof = date.today()

    df = load_mlit_csv(mlit_path)
    koji = load_koji_auto(koji_path)
    kijun = load_kijun_auto(kijun_path)

    # 2. スコープ
    scoped, scope_log = scope_dataframe(df, target, asof)

    # 3. 時点修正（地区一致優先＋直近1年変動率）
    rate_info = annual_rate_for_city(
        koji, kijun, target["市区町村名"],
        target_district=target.get("地区名"),
        asof=asof,
    )
    adjusted = apply_time_adjustment(scoped, asof, rate_info["rate"])

    # 3b. 地区／最寄駅 平均単価をターゲット符号化として df に annotate
    adjusted = annotate_district_mean(adjusted)
    adjusted = annotate_station_mean(adjusted)
    target["_target_district_mean"] = compute_target_district_mean(adjusted, target)
    target["_target_station_mean"] = compute_target_station_mean(adjusted, target)

    # 4. ヘドニック回帰（MLIT全期間で係数推定、n 最大化）
    hed = fit_hedonic(adjusted)

    # 5. 類似度 → top 3
    recent = filter_recent_for_comparison(adjusted, asof, months=DEFAULT_COMPARISON_MONTHS)
    if len(recent) < 3:
        recent = adjusted
        scope_log["warnings"].append(
            f"直近{DEFAULT_COMPARISON_MONTHS}ヶ月の事例が3件未満のため、比準事例選定も全期間から実施"
        )
    scope_log["comparison_recent_count"] = len(recent)
    sim = compute_similarity(recent, target)
    top_cases = top_k(sim, k=3)

    # 6. 個別格差補正
    corrected = apply_correction(top_cases, hed, target)
    breakdown = correction_breakdown(corrected, hed)

    # 6b. 比準表データ生成（鑑定書様式）
    def _kobetsu_pct(beta, tx_val, cx_val):
        if beta is None:
            return 0.0
        contrib = float(beta) * (float(tx_val) - float(cx_val))
        return (_m.exp(contrib) - 1.0) * 100

    coef = hed.get("coefficients", {}) if hed.get("ok") else {}
    target_dir_score = float(DIR_SCORE.get(str(target.get("前面道路:方位", "")).strip(), 0))
    target_fusei = 1.0 if target.get("土地の形状") == "不整形" else 0.0
    # 角地：MLIT データに角地情報無し → 業者明示入力のみ採用（自動デフォルト無し）
    kado_explicit = target.get("角地補正率(%)")
    if kado_explicit is None:
        target_kado = 0.0
    else:
        try:
            target_kado = float(kado_explicit)
        except (TypeError, ValueError):
            target_kado = 0.0

    hijun_rows = []
    hijun_detail_rows = []
    for idx, (_, row) in enumerate(corrected.iterrows()):
        h = hijun_correction_for_case(row, hed, target)
        case_dir_score = float(DIR_SCORE.get(str(row.get("road_dir", "")).strip(), 0))
        case_fusei = 1.0 if row.get("shape") == "不整形" else 0.0
        h["個別格差_角地"] = target_kado
        h["個別格差_方位"] = _kobetsu_pct(
            coef.get("dir_score", {}).get("beta") if "dir_score" in coef else None,
            target_dir_score, case_dir_score)
        h["個別格差_不整形"] = _kobetsu_pct(
            coef.get("D_fuseikei", {}).get("beta") if "D_fuseikei" in coef else None,
            target_fusei, case_fusei)
        # 方位・不整形は正本価格でβ補正済み。個別格差欄は説明表示に留め、
        # 価格へ再乗算しない。角地のみ、明示入力時に apply_correction 側で1回適用。
        h["個別格差_総和_pct"] = 0.0
        h["個別格差_総和_factor"] = 100.0
        h["案件査定価格"] = float(row["corrected_unit_price"])
        case_no = row.get("case_no")
        h["事例番号"] = int(case_no) if pd.notna(case_no) else (idx + 1)
        h["順位"] = "規範性の高い事例" if idx == 0 else f"類似事例{['②','③','④','⑤'][idx-1] if idx-1 < 4 else idx+1}"
        h["取引価格"] = float(row["unit_price"])
        h["地区"] = row.get("district", "")
        h["取引時点"] = str(row.get("transaction_date", ""))
        h["取引四半期"] = row.get("transaction_quarter_str", "") or str(row.get("transaction_date", ""))
        h["面積"] = int(row["area"])
        h["最寄駅"] = row.get("station", "")
        h["駅距離"] = row.get("walk_min", "")
        h["道路種別"] = row.get("road_type", "")
        h["道路幅員"] = row.get("road_width", "")
        h["方位"] = row.get("road_dir", "")
        h["形状"] = row.get("shape", "")
        h["用途地域"] = row.get("zoning", row.get("city_planning", ""))
        h["容積率_pct"] = row.get("floor_area_ratio", "")
        hijun_rows.append(h)
        detail = hijun_breakdown_detail(row, hed, target)
        detail["記号"] = chr(ord("A") + idx)
        detail["事例番号"] = h["事例番号"]
        hijun_detail_rows.append(detail)

    # 7. ヘドニック母集団予測
    hed_pred = _hedonic_population_predict(hed, target)

    # 9. 集約：apply_correction が生成した正本価格系列をそのまま使う。
    assessment = assess(corrected, target["面積(㎡)"])

    # 10. 地域標準価格チェック
    standard_check = _standard_price_for_city(
        koji, kijun, target["市区町村名"], asof,
        target_district=target.get("地区名"),
        target=target,
    )

    # 11. xlsx 出力
    out_dir = Path(out_dir) if out_dir else Path(property_path).parent / "output"
    fname = f"土地査定_{target.get('物件略号', 'NONAME')}_{asof.strftime('%Y%m%d')}.xlsx"
    out_path = out_dir / fname

    ctx = {
        "target": target,
        "asof": asof,
        "scope_log": scope_log,
        "rate_info": rate_info,
        "hedonic": hed,
        "cases": corrected,
        "breakdown": breakdown,
        "assess": assessment,
        "refs": {"hedonic_pred": hed_pred},
        "standard_check": standard_check,
        "hijun_rows": hijun_rows,
        "hijun_detail_rows": hijun_detail_rows,
        "koji_timeseries": _compute_koji_timeseries(
            koji, target["市区町村名"], target.get("地区名"),
            selected_ids=[pt["id"] for pt in standard_check.get("selected_points", [])]
        ),
        "adjusted_full": adjusted,
    }
    write_xlsx(ctx, out_path)
    return out_path


def _copy_to_user_desktop(src_path: Path):
    """v1.2.7: 生成された xlsx をユーザーのデスクトップに自動コピー。
    Windows MAX_PATH（259 文字）制限回避。コピー成功時は Path、失敗時 None。
    """
    home = Path.home()
    candidates = [
        home / "OneDrive" / "デスクトップ",
        home / "OneDrive" / "Desktop",
        home / "Desktop",
    ]
    for dest_dir in candidates:
        try:
            if dest_dir.exists() and dest_dir.is_dir():
                dest_path = dest_dir / src_path.name
                shutil.copy2(src_path, dest_path)
                return dest_path
        except (OSError, PermissionError):
            continue
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("property", help="査定対象物件JSON")
    ap.add_argument("mlit", help="MLIT 取引価格情報CSV")
    ap.add_argument("koji", help="公示地価CSV")
    ap.add_argument("kijun", help="基準地価CSV")
    ap.add_argument("--out", default=None, help="出力ディレクトリ")
    ap.add_argument("--asof", default=None, help="査定時点 YYYY-MM-DD")
    args = ap.parse_args()
    asof = datetime.strptime(args.asof, "%Y-%m-%d").date() if args.asof else None
    out_path = run_pipeline(args.property, args.mlit, args.koji, args.kijun,
                            out_dir=args.out, asof=asof)
    print(f"[OK] 生成完了: {out_path}")
    print("[i] 本出力は机上査定（参考値）です。不動産鑑定評価ではありません。")
    desktop_copy = _copy_to_user_desktop(out_path)
    if desktop_copy:
        print(f"[OK] デスクトップにコピー: {desktop_copy}")
    else:
        print("[!] デスクトップへの自動コピーに失敗しました。手動でコピーしてください。")


if __name__ == "__main__":
    main()
