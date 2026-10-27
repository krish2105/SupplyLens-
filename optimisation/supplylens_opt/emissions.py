"""Assumed CO2e per unit delivered, for the cost / service / CO2 trade-off (F2, multi-objective optimisation).

No supplier record states its transport lane, so the lane is ASSUMED from the quoted lead time, and every factor below
is an assumption to be replaced by the supplier's own data:

| lead time   | assumed lane                         | distance                      |
|-------------|--------------------------------------|-------------------------------|
| <= 3 days   | UK road (articulated HGV)            | 300 km                        |
| 4-7 days    | Continental Europe by road           | 1,500 km                      |
| >= 8 days   | Asia by container ship, then UK road | 18,000 km sea + 300 km road   |

Freight emissions = tonnes carried x km x factor (kg CO2e per tonne-km). Factors are rounded from the UK government's
greenhouse gas reporting conversion factors, "freighting goods" (DESNZ/DEFRA): road HGV about 0.10 and large container
ship about 0.016 kg CO2e per tonne-km. Check them against the current official spreadsheet before reporting externally.
The unit weight (0.5 kg) is assumed: the source data records no weights.
"""
from __future__ import annotations

ROAD_KG_PER_TKM = 0.10
SEA_KG_PER_TKM = 0.016
UNIT_WEIGHT_KG = 0.5

LANES = (  # (max lead time in days, name, road km, sea km)
    (3, "UK road", 300, 0),
    (7, "Europe road", 1500, 0),
    (10_000, "Asia sea + UK road", 300, 18000),
)


def lane_for(lead_time_days: int) -> tuple[str, int, int]:
    for max_days, name, road, sea in LANES:
        if lead_time_days <= max_days:
            return name, road, sea
    raise AssertionError("unreachable")


def grams_per_unit(lead_time_days: int, unit_weight_kg: float = UNIT_WEIGHT_KG) -> int:
    """Grams CO2e to deliver one unit on the lane assumed for this lead time (rounded to whole grams)."""
    _, road, sea = lane_for(lead_time_days)
    tonnes = unit_weight_kg / 1000
    return round(tonnes * (road * ROAD_KG_PER_TKM + sea * SEA_KG_PER_TKM) * 1000)


ASSUMPTIONS = [
    "lane assumed from the quoted lead time: <= 3 days UK road 300 km; 4-7 days Europe road 1,500 km; "
    ">= 8 days Asia container ship 18,000 km + UK road 300 km",
    f"factors: road {ROAD_KG_PER_TKM} and sea {SEA_KG_PER_TKM} kg CO2e per tonne-km (rounded, UK DESNZ freighting goods)",
    f"unit weight {UNIT_WEIGHT_KG} kg (assumed; the data records no weights)",
]
