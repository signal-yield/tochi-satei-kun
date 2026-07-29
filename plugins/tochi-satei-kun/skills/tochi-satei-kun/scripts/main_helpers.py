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

"""main_helpers 互換 shim（v1.4.1 で main_helpers_geo + main_helpers_koji に分割）。

Cowork 配布層 truncate ライン（~17KB）対策で本ファイルを 2 つに分割しましたが、
main.py 等の既存呼び出し側を変更しなくて済むように再エクスポート shim として残します。

新規コードからは main_helpers_geo / main_helpers_koji を直接 import してください。
"""
from main_helpers_geo import (
    SOUTH_FACING,
    _CITY_CODE_TO_SHORT,
    _short_koji_id,
    _zoning_category,
    _normalize_chome,
    _score_koji_point,
    _hedonic_population_predict,
)
from main_helpers_koji import (
    _interpolate_price_at_asof,
    _standard_price_for_city,
    _label_for_standard_points,
    _compute_koji_timeseries,
)
