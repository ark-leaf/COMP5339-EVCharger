"""Existing structured-address scoring and metre-based distance rules."""
from __future__ import annotations

import difflib
import math
import re
import unicodedata
import pandas as pd

from pipeline.data_aug.nsw_evc_aug_config import (
    COORDINATE_THRESHOLD_M, ADDRESS_THRESHOLD, STREET_THRESHOLD, FULL_ADDRESS_THRESHOLD,
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
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def clean_number(value: str) -> str:
    value = re.sub(r"\s+", "", value.lower())
    return value.replace("–", "-").replace("—", "-")


def address_parts(address, postcode_value="") -> dict[str, str]:
    raw = unicodedata.normalize("NFKC", text(address)).lower()
    raw = raw.replace("new south wales", " ").replace("australia", " ")
    raw = re.sub(r"\bnsw\b", " ", raw)

    postcode_candidates = POSTCODE_RE.findall(text(postcode_value))
    if postcode_candidates:
        postcode = postcode_candidates[-1]
    else:
        address_postcodes = POSTCODE_RE.findall(raw)
        postcode = address_postcodes[-1] if address_postcodes else ""
        if postcode:
            # Remove only the final postcode, not every four-digit number.
            raw = re.sub(rf"(?<!\d){re.escape(postcode)}(?!\d)\s*$", " ", raw)

    # Turn punctuation such as commas into separators while preserving
    # hyphens/slashes used in Australian address numbers such as 20-22 or
    # 85/91.  Keeping commas attached to tokens would hide street types like
    # ``drive,`` from the alias table.
    raw = re.sub(r"[^a-z0-9/-]+", " ", raw)
    tokens = [STREET_TYPES.get(token, token) for token in raw.split()]
    number_matches = list(NUMBER_RE.finditer(raw))
    house_number = clean_number(number_matches[0].group(0)) if number_matches else ""

    street_core = ""
    for type_index, token in enumerate(tokens):
        if token not in set(STREET_TYPES.values()):
            continue
        number_index = None
        for index in range(type_index - 1, max(-1, type_index - 8), -1):
            if index >= 0 and NUMBER_RE.fullmatch(tokens[index]):
                number_index = index
                break
        if number_index is not None:
            house_number = clean_number(tokens[number_index])
            street_tokens = tokens[number_index + 1 : type_index]
        else:
            street_tokens = tokens[max(0, type_index - 4) : type_index]
        if street_tokens:
            street_core = " ".join(street_tokens + [token])
            break

    normalised = " ".join(tokens)
    return {
        "postcode": postcode,
        "house_number": house_number,
        "street_core": street_core,
        "normalised": normalised,
    }


def similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return difflib.SequenceMatcher(None, left, right).ratio()


def token_similarity(left: str, right: str) -> float:
    left_tokens, right_tokens = set(left.split()), set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    return 2 * len(left_tokens & right_tokens) / (len(left_tokens) + len(right_tokens))


def address_score(source: dict[str, str], candidate: dict[str, str]) -> float:
    street = similarity(source["street_core"], candidate["street_core"])
    full = similarity(source["normalised"], candidate["normalised"])
    postcode = float(bool(source["postcode"] and source["postcode"] == candidate["postcode"]))
    house_number = float(
        bool(source["house_number"] and source["house_number"] == candidate["house_number"])
    )
    return 0.55 * street + 0.20 * full + 0.15 * postcode + 0.10 * house_number


def address_accepted(source: dict[str, str], candidate: dict[str, str], score: float) -> bool:
    street = similarity(source["street_core"], candidate["street_core"])
    full = similarity(source["normalised"], candidate["normalised"])
    postcode_match = bool(source["postcode"] and source["postcode"] == candidate["postcode"])
    house_match = bool(source["house_number"] and source["house_number"] == candidate["house_number"])
    return (
        score >= ADDRESS_THRESHOLD
        and (street >= STREET_THRESHOLD or full >= FULL_ADDRESS_THRESHOLD)
        and (postcode_match or house_match)
    )


def distance_metres(lat_a, lon_a, lat_b, lon_b) -> float:
    radius = 6_371_000.0
    phi_a, phi_b = math.radians(float(lat_a)), math.radians(float(lat_b))
    d_phi = math.radians(float(lat_b) - float(lat_a))
    d_lambda = math.radians(float(lon_b) - float(lon_a))
    value = math.sin(d_phi / 2) ** 2 + math.cos(phi_a) * math.cos(phi_b) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(min(1.0, value)))
