"""Area code mapping and weather centroids — single source of truth.

The `areas` table holds the canonical set (TK, KS, HK, TH, CB, HR, CG, SK, KY, SYS).
Upstream sources sometimes spell area names differently (japanesepower.org's CSV
uses "Chuubu" / "Chuugoku" with double-u; Open-Meteo doesn't know about JEPX
areas at all and needs lat/lon centroids).

This module keeps those mappings in one place so future cleanup is mechanical.
"""

from __future__ import annotations

# Maps japanesepower.org CSV column names → our canonical area codes.
# `System` is the Japan-wide reference price/demand series.
JAPOWER_AREA_MAP: dict[str, str] = {
    "System": "SYS",
    "Hokkaido": "HK",
    "Tohoku": "TH",
    "Tokyo": "TK",
    "Chuubu": "CB",
    "Hokuriku": "HR",
    "Kansai": "KS",
    "Chuugoku": "CG",
    "Shikoku": "SK",
    "Kyushu": "KY",
}

# (latitude, longitude) of one representative city per area — used as the
# point-of-fetch for Open-Meteo. SYS is excluded (synthetic, no physical
# location). Coordinates: prefecture capital cities.
WEATHER_CENTROIDS: dict[str, tuple[float, float]] = {
    "HK": (43.0642, 141.3469),  # Sapporo
    "TH": (38.2682, 140.8694),  # Sendai
    "TK": (35.6762, 139.6503),  # Tokyo
    "CB": (35.1815, 136.9066),  # Nagoya
    "HR": (36.5946, 136.6256),  # Kanazawa
    "KS": (34.6937, 135.5023),  # Osaka
    "CG": (34.3853, 132.4553),  # Hiroshima
    "SK": (34.3401, 134.0434),  # Takamatsu
    "KY": (33.5904, 130.4017),  # Fukuoka
}
