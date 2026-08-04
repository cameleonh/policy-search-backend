"""Region name canonicalization for Korean administrative districts.

Ports the CTPV_CANON mapping from youth-search to normalize 시도명
variants (전라남도, 광주 → 전남광주통합특별시, etc.).
"""

from __future__ import annotations

import re

_ZWSP = "\u200b"

# Maps common short/old names to the current official name used by 온통청년.
_CTPV_CANON: dict[str, str] = {
    "전라남도": "전남광주통합특별시",
    "광주광역시": "전남광주통합특별시",
    "전남": "전남광주통합특별시",
    "광주": "전남광주통합특별시",
    "강원도": "강원특별자치도",
    "강원": "강원특별자치도",
    "전라북도": "전북특별자치도",
    "전북": "전북특별자치도",
    "제주도": "제주특별자치도",
    "제주": "제주특별자치도",
    "제주특별자치도": "제주특별자치도",
    "세종시": "세종특별자치시",
    "세종": "세종특별자치시",
    "서울": "서울특별시",
    "서울시": "서울특별시",
    "부산": "부산광역시",
    "대구": "대구광역시",
    "인천": "인천광역시",
    "대전": "대전광역시",
    "울산": "울산광역시",
    "경기": "경기도",
    "경기도": "경기도",
    "충북": "충청북도",
    "충남": "충청남도",
    "경북": "경상북도",
    "경남": "경상남도",
}


def _clean(value: object) -> str:
    """Strip HTML tags, decode entities, normalize whitespace."""
    s = re.sub(r"<[^>]+>", "", str(value or ""))
    import html

    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).replace(_ZWSP, "").strip()


def canon_region(name: str) -> str:
    """Canonicalize a Korean region name to the official form."""
    cleaned = _clean(name)
    return _CTPV_CANON.get(cleaned, cleaned)
