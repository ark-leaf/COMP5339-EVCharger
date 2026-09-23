# 0. Locations
# 0.1. File Locations
from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC_DATA_FILE_LOCATION = str(ROOT / "src_data")
# - Outcome of Step 1: Data Cleaning
CLEAN_SRC_DATA_FILE_LOCATION = str(ROOT / "clean_src_data")
# - Outcome of Step 2: Data Augmentation
AUG_DATA_FILE_LOCATION = str(ROOT / "aug_data")
# - Outcome of Step 3: Final Result
RESULT_DATA_FILE_LOCATION = str(ROOT / "result_data")

# 0.2. Data Sources

# 0.2.1. NSW EV Charging Locations - NSW Transport Open Data
NSW_TRANSPORT_API_TOKEN = "comp5339-usyd"
NSW_EV_CHARGING_SRC_FILE_URL = "https://opendata.transport.nsw.gov.au/data/dataset/be1c4de4-4517-4bd0-8a09-2965ddfc7179/resource/7bbb6461-e52d-4fe7-ace4-a15c30198de0/download/ev_20251216.csv"
NSW_EV_CHARGING_SRC_FILE_NAME = "nsw_ev_charging.csv"
NSW_EV_CHARGING_SRC_FILE = f"{SRC_DATA_FILE_LOCATION}/{NSW_EV_CHARGING_SRC_FILE_NAME}"
NSW_EV_CHARGING_CLEANED_FILE = f"{CLEAN_SRC_DATA_FILE_LOCATION}/{NSW_EV_CHARGING_SRC_FILE_NAME}"
NSW_EV_CHARGING_AUG_FILE = f"{AUG_DATA_FILE_LOCATION}/{NSW_EV_CHARGING_SRC_FILE_NAME}"

# 0.2.2. AUS ASGS
AUS_ASGS_LV4_URL = "https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs/edition-4-july-2026-june-2031/access-and-downloads/digital-boundary-files/SA4_2026_AUST_SHP_GDA2020.zip"
AUS_ASGS_LV4_ZIP_FILE_NAME = "SA4_2026_AUST_SHP_GDA2020.zip"
AUS_ASGS_LV4_FILE = f"{SRC_DATA_FILE_LOCATION}/{AUS_ASGS_LV4_ZIP_FILE_NAME}"

# 0.2.3. OpenChargerMap
OCM_ENDPOINT = "https://api.openchargemap.io/v3/poi/"
OCM_API_KEY = os.environ.get("OCM_API_KEY", "")
OCM_USER_AGENT = "COMP5339-EVCharger-ass1/0.1"
OCM_REFRESH_SNAPSHOT = os.getenv("OCM_REFRESH_SNAPSHOT", "0") == "1"
OCM_SNAPSHOT_FILE = Path(f"{RESULT_DATA_FILE_LOCATION}/ocm_ev_charging_snapshot.json")
OCM_SNAPSHOT_METADATA_FILE = Path(f"{RESULT_DATA_FILE_LOCATION}/ocm_ev_charging_snapshot_metadata.json")
# 0.2.4. OpenStreetMap API
OSM_API_PROD = "https://api.openstreetmap.org/api/"
OSM_API_SANDBOX = "https://master.apis.dev.openstreetmap.org/"

# 0.2.5. Address Enrichment (Nominatim / Google Geocoding)
NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
GOOGLE_GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"
ADDRESS_ENRICHER_USE_NOMINATIM = True
ADDRESS_ENRICHER_GOOGLE_API_KEY = ""
ADDRESS_ENRICHER_CACHE_FILE = Path(RESULT_DATA_FILE_LOCATION) / "task2_nominatim_cache.json"
# Replays are offline. Explicitly opt in only when new source coordinates need geocoding.
ADDRESS_ENRICHER_ALLOW_NETWORK = os.getenv("ADDRESS_ENRICHER_ALLOW_NETWORK", "0") == "1"

# Initialize AddressEnricher instance (lazy import to avoid circular dependencies)
_ADDRESS_ENRICHER = None

def get_address_enricher():
    """Get or initialize the global AddressEnricher instance.

    Returns:
        AddressEnricher: Configured address enricher instance.
    """
    global _ADDRESS_ENRICHER
    if _ADDRESS_ENRICHER is None:
        from data_utils.address_enricher import AddressEnricher
        _ADDRESS_ENRICHER = AddressEnricher(
            nominatim_url=NOMINATIM_URL,
            google_geocoding_url=GOOGLE_GEOCODING_URL,
            use_nominatim=ADDRESS_ENRICHER_USE_NOMINATIM,
            google_api_key=ADDRESS_ENRICHER_GOOGLE_API_KEY,
            nominatim_user_agent="COMP5339-EVCharger-ass1/0.1 (https://github.com/ark-leaf/COMP5339-EVCharger)",
            cache_file=ADDRESS_ENRICHER_CACHE_FILE,
            allow_network=ADDRESS_ENRICHER_ALLOW_NETWORK,
        )
    return _ADDRESS_ENRICHER

# 2. Data Augmentation: Enrich NSW EV Charging Locations details
TASK3_COORDINATE_PRECISION = 6
TASK3_MAX_NEAR_DISTANCE_METRES = 5.0
TASK3_MIN_NEAREST_GAP_METRES = 20.0
TASK3_OCM_SEARCH_RADIUS_KM = 5
TASK3_OCM_SEARCH_MAXRESULTS = 100
TASK3_OCM_REQUEST_DELAY_SECONDS = 0.1
TASK3_OCM_NSW_BOUNDING_BOX = "(-37.6,140.8),(-27.9,154.3)"
TASK3_STREET_TYPE_ALIASES = {
    "alley": "aly", "aly": "aly", "avenue": "ave", "ave": "ave",
    "boulevard": "bvd", "bvd": "bvd", "circuit": "cct", "cct": "cct",
    "close": "cl", "cl": "cl", "crescent": "cres", "cres": "cres",
    "drive": "dr", "dr": "dr", "esplanade": "esp", "esp": "esp",
    "highway": "hwy", "hwy": "hwy", "lane": "ln", "ln": "ln",
    "parade": "pde", "pde": "pde", "place": "pl", "pl": "pl",
    "road": "rd", "rd": "rd", "street": "st", "st": "st",
    "terrace": "tce", "tce": "tce", "way": "way", "wy": "way",
}
TASK3_NUMBER_RE = re.compile(r"^\d+[a-z]?(?:[-/]\d+[a-z]?)?$")


def __getattr__(name):
    """Lazy compatibility for earlier scripts; the active stage modules own code."""
    if name in {"GET_NSW_EV_COLUMN_AUGMENTATION_CCS", "GET_NSW_EV_COLUMN_AUGMENTATION_MULTISOURCE", "TASK3_FINAL_AUDIT_FILE", "get_ocm_details"}:
        from pipeline.data_aug import nsw_evc_aug_config
        return getattr(nsw_evc_aug_config, name)
    if name == "address_processor":
        from pipeline.data_clean.nsw_evc_data_clean_utils import address_processor
        return address_processor
    if name.startswith("_task3_"):
        from pipeline.data_aug import ocm_reference
        return getattr(ocm_reference, name)
    raise AttributeError(f"module config has no attribute {name!r}")
