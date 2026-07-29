# Copyright 2026 Koichi Matsuda / SignalYield Advisory
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""基準地価入力を任意化したCLI互換性の回帰テスト。"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from main import run_pipeline

SAMPLES = ROOT / "samples"


def test_pipeline_runs_without_kijun(tmp_path):
    """正規経路: property / MLIT / 地価公示の3入力で完走する。"""
    out_path = run_pipeline(
        str(SAMPLES / "sample_property.json"),
        str(SAMPLES / "sample_mlit.csv"),
        str(SAMPLES / "sample_koji.csv"),
        out_dir=str(tmp_path),
    )
    assert out_path.exists()
    assert out_path.suffix == ".xlsx"


def test_pipeline_keeps_legacy_kijun_argument(tmp_path):
    """後方互換: 旧4入力形式も引き続き完走する。"""
    out_path = run_pipeline(
        str(SAMPLES / "sample_property.json"),
        str(SAMPLES / "sample_mlit.csv"),
        str(SAMPLES / "sample_koji.csv"),
        str(SAMPLES / "sample_kijun.csv"),
        out_dir=str(tmp_path),
    )
    assert out_path.exists()
    assert out_path.suffix == ".xlsx"
