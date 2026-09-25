# USYD CODE CITATION ACKNOWLEDGEMENT
# I declare that the original configuration came from the team's implementation.
# During later integration, OpenAI Codex assisted with portable paths,
# environment-only OCM key handling and cached get_address_enricher() settings.

# 0. Locations
# 0.1. Project Root (absolute path for portability)
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.resolve()

# 0.2. File Locations (absolute paths for portability across working directories)
DATA_ROOT = PROJECT_ROOT / "data"
SRC_DATA_FILE_LOCATION = DATA_ROOT / "src_data"
# - Outcome of Step 1: Data Cleaning
CLEAN_SRC_DATA_FILE_LOCATION = DATA_ROOT / "clean_src_data"
# - Outcome of Step 2: Data Augmentation
AUG_DATA_FILE_LOCATION = DATA_ROOT / "aug_data"
# - Outcome of Step 3: Final Result
RESULT_DATA_FILE_LOCATION = DATA_ROOT / "result_data"

# 0.3. Data Sources

# 0.3.1. NSW EV Charging Locations - NSW Transport Open Data
NSW_TRANSPORT_API_TOKEN = "comp5339-usyd"
NSW_EV_CHARGING_SRC_FILE_URL = "https://opendata.transport.nsw.gov.au/data/dataset/be1c4de4-4517-4bd0-8a09-2965ddfc7179/resource/7bbb6461-e52d-4fe7-ace4-a15c30198de0/download/ev_20251216.csv"
NSW_EV_CHARGING_SRC_FILE_NAME = "nsw_ev_charging.csv"
NSW_EV_CHARGING_SRC_FILE = SRC_DATA_FILE_LOCATION / NSW_EV_CHARGING_SRC_FILE_NAME
NSW_EV_CHARGING_CLEANED_FILE = CLEAN_SRC_DATA_FILE_LOCATION / NSW_EV_CHARGING_SRC_FILE_NAME
NSW_EV_CHARGING_AUG_FILE = AUG_DATA_FILE_LOCATION / NSW_EV_CHARGING_SRC_FILE_NAME

# 0.3.2. AUS ASGS
AUS_ASGS_LV4_URL = "https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs/edition-4-july-2026-june-2031/access-and-downloads/digital-boundary-files/SA4_2026_AUST_SHP_GDA2020.zip"
AUS_ASGS_LV4_ZIP_FILE_NAME = "SA4_2026_AUST_SHP_GDA2020.zip"
AUS_ASGS_LV4_FILE = SRC_DATA_FILE_LOCATION / AUS_ASGS_LV4_ZIP_FILE_NAME

# 0.3.3. OpenChargerMap
OCM_ENDPOINT = "https://api.openchargemap.io/v3/poi/"
OCM_API_KEY = os.environ.get("OCM_API_KEY", "")
OCM_USER_AGENT = "COMP5339-EVCharger-ass1/0.1"
OCM_REFRESH_SNAPSHOT = False
OCM_SNAPSHOT_FILE = RESULT_DATA_FILE_LOCATION / "ocm_ev_charging_snapshot.json"
OCM_SNAPSHOT_METADATA_FILE = RESULT_DATA_FILE_LOCATION / "ocm_ev_charging_snapshot_metadata.json"
# 0.2.4. OpenStreetMap API
OSM_API_PROD = "https://api.openstreetmap.org/api/"
OSM_API_SANDBOX = "https://master.apis.dev.openstreetmap.org/"

# 0.2.5. Address Enrichment (Nominatim / Google Geocoding)
NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
GOOGLE_GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"
ADDRESS_ENRICHER_USE_NOMINATIM = True
ADDRESS_ENRICHER_GOOGLE_API_KEY = ""
ADDRESS_ENRICHER_CACHE_FILE = RESULT_DATA_FILE_LOCATION / "task2_nominatim_cache.json"
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

# Task 3 matching settings live in pipeline/data_aug/nsw_evc_aug_config.py.
