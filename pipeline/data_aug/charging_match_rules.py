"""Distance and address evidence for Task 3 station matching.

Core parsing and scoring were supplied by the student. Helper implementation,
syntax repair and integration checks were AI-assisted.
"""
from __future__ import annotations

import difflib
import math
import re
import unicodedata
import pandas as pd

from pipeline.data_aug.nsw_evc_aug_config import (
    ADDRESS_THRESHOLD,
    FULL_ADDRESS_THRESHOLD,
    STREET_THRESHOLD,
)

STREET_TYPES = {
    "street": "st", "st": "st", "road": "rd", "rd": "rd",
    "avenue": "ave", "ave": "ave", "drive": "dr", "dr": "dr",
    "highway": "hwy", "hwy": "hwy", "lane": "ln", "ln": "ln",
    "place": "pl", "pl": "pl", "parade": "pde", "pde": "pde",
    "crescent": "cres", "cres": "cres", "boulevard": "bvd", "bvd": "bvd",
    "terrace": "tce", "tce": "tce", "close": "cl", "cl": "cl",
    "circuit": "cct", "cct": "cct", "esplanade": "esp", "esp": "esp",
    "way": "way", "wy": "way",
}
NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])\d+[A-Za-z]?(?:\s*[-/]\s*\d+[A-Za-z]?)?(?![A-Za-z0-9])")
POSTCODE_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")


def text(value) -> str:
    """Return a stripped string, treating missing scalar values as empty."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def clean_number(value: str) -> str:
    raw = re.sub(r"\s+", "", text(value).lower())
    raw = raw.replace("–", "-").replace("—", "-")

    pieces = re.split(r"([/-])", raw)
    cleaned = []
    for piece in pieces:
        match = re.fullmatch(r"0*(\d+)([a-z]?)", piece)
        if match:
            cleaned.append(f"{int(match.group(1))}{match.group(2)}")
        else:
            cleaned.append(piece)
    return "".join(cleaned)


def address_parts(address, postcode_value='') -> dict[str, str]:
    """Extract comparable street, house-number and postcode evidence."""
    raw = unicodedata.normalize("NFKD", text(address).casefold())
    raw = "".join(char for char in raw if not unicodedata.combining(char))
    raw = raw.replace("–", "-").replace("—", "-")
    raw = re.sub(r"(\d)\s*([/-])\s*(\d)", r"\1\2\3", raw)
    raw = re.sub(
        r"\baustralia\b|\bnew south wales\b|\bnsw\b",
        " ",
        raw,
    )
    raw = re.sub(r"[,\s]+$", "", raw)

    # Prefer a postcode printed in the address. PCODE may have been repaired
    # or may conflict with the original source value.
    printed = re.search(r"(?<!\d)(\d{4})(?!\d)\s*$", raw)
    supplied = POSTCODE_RE.search(text(postcode_value))
    if printed:
        postcode = printed.group(1)
        raw = raw[:printed.start()]
    else:
        postcode = supplied.group(1) if supplied else ""

    segments = [
        segment.strip()
        for segment in re.split(r"[,;]", raw)
        if segment.strip()
    ]
    token_groups = []
    for segment in segments:
        cleaned = re.sub(r"[^a-z0-9/-]+", " ", segment)
        token_groups.append([
            STREET_TYPES.get(token, token)
            for token in cleaned.split()
        ])

    normalised = " ".join(
        token for group in token_groups for token in group
    )
    street_core = ""
    house_number = ""
    street_labels = set(STREET_TYPES.values())

    for tokens in token_groups:
        street_at = next(
            (i for i, token in enumerate(tokens) if token in street_labels),
            None,
        )
        if street_at is None:
            continue

        # Use the number nearest the street name, not a shop/unit number
        # from an earlier address segment.
        number_at = next(
            (
                i for i in range(street_at - 1, -1, -1)
                if NUMBER_RE.fullmatch(tokens[i])
            ),
            None,
        )
        start = number_at + 1 if number_at is not None else max(0, street_at - 3)
        street_core = " ".join(tokens[start:street_at + 1])
        if number_at is not None:
            house_number = clean_number(tokens[number_at])
        break

    return {
        "postcode": postcode,
        "house_number": house_number,
        "street_core": street_core,
        "normalised": normalised,
    }


def similarity(left: str, right: str) -> float:
    """Measure character-level similarity only when both values are present."""
    first, second = text(left), text(right)
    if not first or not second:
        return 0.0
    return difflib.SequenceMatcher(None, first, second).ratio()


def token_similarity(left: str, right: str) -> float:
    """Compare street words without requiring identical word order."""
    first, second = set(text(left).split()), set(text(right).split())
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


def address_score(source: dict[str, str], candidate: dict[str, str]) -> float:
    """Score fuzzy address evidence; explicit conflicts are checked separately."""
    street = max(
        similarity(source["street_core"], candidate["street_core"]),
        token_similarity(source["street_core"], candidate["street_core"]),
    )
    full = similarity(source["normalised"], candidate["normalised"])
    postcode = float(
        bool(
            source["postcode"]
            and source["postcode"] == candidate["postcode"]
        )
    )
    house = float(
        bool(
            source["house_number"]
            and source["house_number"] == candidate["house_number"]
        )
    )
    return 0.55 * street + 0.20 * full + 0.15 * postcode + 0.10 * house


def address_accepted(source: dict[str, str], candidate: dict[str, str], score: float) -> bool:
    """Accept address evidence only with street agreement and no explicit conflict."""
    if not math.isfinite(score) or score < ADDRESS_THRESHOLD:
        return False

    street = max(
        similarity(source["street_core"], candidate["street_core"]),
        token_similarity(source["street_core"], candidate["street_core"]),
    )
    full = similarity(source["normalised"], candidate["normalised"])
    if street < STREET_THRESHOLD and full < FULL_ADDRESS_THRESHOLD:
        return False

    # A high fuzzy score must not override an explicit contradiction.
    for field in ("postcode", "house_number"):
        left = source[field]
        right = candidate[field]
        if left and right and left != right:
            return False

    postcode_matches = bool(
        source["postcode"]
        and source["postcode"] == candidate["postcode"]
    )
    house_matches = bool(
        source["house_number"]
        and source["house_number"] == candidate["house_number"]
    )
    return postcode_matches or house_matches


def distance_metres(lat_a, lon_a, lat_b, lon_b) -> float:
    """Return great-circle distance in metres, or infinity for invalid points."""
    values = (lat_a, lon_a, lat_b, lon_b)
    if any(isinstance(value, bool) for value in values):
        return math.inf
    try:
        a_lat, a_lon, b_lat, b_lon = map(float, values)
    except (TypeError, ValueError):
        return math.inf

    if not all(math.isfinite(value) for value in (a_lat, a_lon, b_lat, b_lon)):
        return math.inf
    if not (
        -90 <= a_lat <= 90 and -90 <= b_lat <= 90
        and -180 <= a_lon <= 180 and -180 <= b_lon <= 180
    ):
        return math.inf

    lat1 = math.radians(a_lat)
    lat2 = math.radians(b_lat)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(b_lon - a_lon)
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )
    return 2 * 6_371_000 * math.asin(
        math.sqrt(min(1.0, max(0.0, haversine)))
    )
