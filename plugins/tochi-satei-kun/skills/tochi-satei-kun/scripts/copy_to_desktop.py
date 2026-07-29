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

"""デスクトップに xlsx をコピー（v1.2.8、独立ヘルパー）。

main.py のパイプライン完走後、xlsx をユーザーのデスクトップへ自動コピー。
Windows の MAX_PATH 259 文字制限により Cowork/Claude Desktop サンドボックス
配下の深いパスでは Excel が xlsx を開けないため、必ず短いパスへ配置する。

Usage:
    python copy_to_desktop.py <xlsx_path>

複数の Desktop パス候補を順に試行し、最初に存在するものを採用：
  1. ~/OneDrive/デスクトップ   （日本語 Windows + OneDrive 同期）
  2. ~/OneDrive/Desktop        （英語 Windows + OneDrive 同期）
  3. ~/Desktop                 （ローカル / Mac / Linux）
"""
import shutil
import sys
from pathlib import Path


def copy_to_desktop(src_path: Path):
    """xlsx をユーザーのデスクトップにコピー。
    Returns: コピー先 Path（成功時）／ None（全候補で失敗時）。
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
    if len(sys.argv) != 2:
        print("Usage: python copy_to_desktop.py <xlsx_path>")
        sys.exit(2)
    src = Path(sys.argv[1])
    if not src.exists():
        print(f"[!] ファイルが見つかりません: {src}")
        sys.exit(1)
    dest = copy_to_desktop(src)
    if dest:
        print(f"[OK] デスクトップにコピー: {dest}")
        sys.exit(0)
    else:
        print("[!] デスクトップへの自動コピー失敗。以下を手動でコピーしてください：")
        print(f"    {src}")
        sys.exit(1)


if __name__ == "__main__":
    main()
