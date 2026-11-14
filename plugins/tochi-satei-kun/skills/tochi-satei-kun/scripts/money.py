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

"""円建て金額の整数化ルール（xlsx と JSON の共通正本）。

**採用する丸めルール: 四捨五入（ROUND_HALF_UP）で整数円**

xlsx 出力と JSON 出力が同じ査定値から別々に整数化していたため、採用単価が
1 円ずれることがあった（xlsx 側が `int()` による切り捨て、JSON 側が Python
組み込み `round()` による偶数丸め）。表示経路ごとに整数化するのをやめ、
本モジュールの `round_money()` だけを通す。

`round()` ではなく `Decimal(ROUND_HALF_UP)` を使うのは、組み込み `round()` が
偶数丸め（banker's rounding）で、ちょうど 0.5 のときに 0.5 → 0、1.5 → 2 と
金額の扱いとして直感に反するため。金額は日本の商習慣どおり四捨五入する。

査定計算そのものは変更しない。丸めは表示・出力のためだけに行う。
"""
import math
from decimal import Decimal, ROUND_HALF_UP

__all__ = ["round_money"]


def round_money(value):
    """円建て金額を四捨五入して整数円にする。None / NaN / Inf は None を返す。"""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return int(Decimal(repr(f)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
