# USYD CODE CITATION ACKNOWLEDGEMENT
# I declare that OpenAI Codex assisted with reverse-geocoding cache replay,
# network opt-in, request validation and failure handling in AddressEnricher.

"""Address enrichment using free geocoding APIs (OpenStreetMap Nominatim and Google Geocoding)."""
import time
import requests
from typing import Optional, Tuple
import logging
import json
import math
from pathlib import Path
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AddressEnricher:
    """Convert GPS coordinates to addresses using free geocoding APIs."""

    def __init__(
        self,
        nominatim_url: str,
        google_geocoding_url: str,
        use_nominatim: bool = True,
        google_api_key: Optional[str] = None,
        nominatim_user_agent: str = "YDataUtils Address Enricher",
        nominatim_zoom: int = 18,
        request_timeout: int = 10,
        cache_file: Optional[Path] = None,
        allow_network: bool = False,
    ):
        """Initialize geocoding converter with preferred API.

        Args:
            nominatim_url (str): OpenStreetMap Nominatim reverse geocoding endpoint URL.
                Required parameter, must be provided from config.py (no default).
            google_geocoding_url (str): Google Geocoding API endpoint URL.
                Required parameter, must be provided from config.py (no default).
            use_nominatim (bool, optional): If True, use OpenStreetMap Nominatim (free, no API key).
                If False, use Google Geocoding API. Defaults to True.
            google_api_key (str, optional): Google Geocoding API key for authentication.
                Only needed if use_nominatim is False. Defaults to None.
            nominatim_user_agent (str, optional): User-Agent header string for Nominatim API requests.
                Defaults to "YDataUtils Address Enricher".
            nominatim_zoom (int, optional): Zoom level for Nominatim (1-18, higher = more detailed).
                Defaults to 18 (maximum detail).
            request_timeout (int, optional): Timeout duration for API requests in seconds.
                Defaults to 10 seconds.

        Raises:
            TypeError: If nominatim_url or google_geocoding_url is not provided.
        """
        self.use_nominatim = use_nominatim
        self.google_api_key = google_api_key
        self.nominatim_url = nominatim_url
        self.nominatim_headers = {'User-Agent': nominatim_user_agent}
        self.google_geocoding_url = google_geocoding_url
        self.nominatim_zoom = nominatim_zoom
        self.request_timeout = request_timeout
        self.request_count = 0
        self.last_request_time = 0
        self.cache_file = Path(cache_file) if cache_file else None
        self.allow_network = allow_network
        self.cache = json.loads(self.cache_file.read_text(encoding="utf-8")) if self.cache_file and self.cache_file.exists() else {}

    def _reverse_geocode_nominatim(self, latitude: float, longitude: float) -> Optional[dict]:
        """Reverse geocode using OpenStreetMap Nominatim.

        Args:
            latitude (float): Latitude coordinate.
            longitude (float): Longitude coordinate.

        Returns:
            dict or None: Dictionary with address details or None if request fails.

        """
        latitude, longitude = float(latitude), float(longitude)
        if not (math.isfinite(latitude) and math.isfinite(longitude) and -90 <= latitude <= 90 and -180 <= longitude <= 180):
            return None
        key = f"{self.nominatim_url}|{self.nominatim_zoom}|{latitude:.7f},{longitude:.7f}"
        if key in self.cache:
            return self.cache[key]["response"]
        if not self.allow_network:
            raise RuntimeError("Missing Task 2 geocoding cache. Set ADDRESS_ENRICHER_ALLOW_NETWORK=1 for a one-time refresh.")
        # One machine/thread, <= 1 request/second; cache every successful response.
        time_since_last = time.time() - self.last_request_time
        if time_since_last < 1.1:
            time.sleep(1.1 - time_since_last)

        try:
            params = {
                'lat': latitude,
                'lon': longitude,
                'format': 'json',
                'zoom': self.nominatim_zoom,
                'addressdetails': 1
            }

            response = requests.get(
                self.nominatim_url,
                params=params,
                headers=self.nominatim_headers,
                timeout=self.request_timeout
            )
            self.last_request_time = time.time()
            self.request_count += 1

            if response.status_code == 200:
                payload = response.json()
                self.cache[key] = {
                    "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                    "response": payload,
                }
                if self.cache_file:
                    self.cache_file.parent.mkdir(parents=True, exist_ok=True)
                    temporary = self.cache_file.with_suffix(".json.tmp")
                    temporary.write_text(json.dumps(self.cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    temporary.replace(self.cache_file)
                return payload
            else:
                raise RuntimeError(f"Nominatim returned HTTP {response.status_code}; stopping without silently changing Task 2 output.")

        except requests.exceptions.RequestException as e:
            raise RuntimeError("Task 2 geocoding request failed; rerun after checking connectivity.") from e
        finally:
            self.last_request_time = time.time()

    def _reverse_geocode_google(self, latitude: float, longitude: float) -> Optional[dict]:
        """Reverse geocode using Google Geocoding API.

        Args:
            latitude (float): Latitude coordinate.
            longitude (float): Longitude coordinate.

        Returns:
            dict or None: Dictionary with address details or None if request fails.

        Note:
            - Requires API key.
            - Free tier: 25,000 requests/day (requires billing account).
        """
        if not self.google_api_key:
            logger.error("Google API key not provided")
            return None

        try:
            params = {
                'latlng': f'{latitude},{longitude}',
                'key': self.google_api_key
            }

            response = requests.get(self.google_geocoding_url, params=params, timeout=self.request_timeout)
            self.request_count += 1

            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"Google API error: {response.status_code}")
                return None

        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {e}")
            return None

    def _extract_address_from_nominatim(self, data: dict) -> Tuple[str, str, str, str]:
        """Extract address components from Nominatim response.

        Args:
            data (dict): Response dictionary from Nominatim API.

        Returns:
            tuple: (street, suburb, state, postcode)
        """
        if not data or 'address' not in data:
            return '', '', '', ''

        addr = data['address']

        # Extract components
        street_number = addr.get('house_number', '')
        street_name = addr.get('road', addr.get('street', ''))
        suburb = addr.get('suburb', addr.get('city', addr.get('town', '')))
        state = addr.get('state', 'NSW')
        postcode = addr.get('postcode', '')

        # Format street
        if street_number and street_name:
            street = f"{street_number} {street_name}"
        elif street_name:
            street = street_name
        else:
            street = ''

        return street, suburb, state, postcode

    def _extract_address_from_google(self, data: dict) -> Tuple[str, str, str, str]:
        """Extract address components from Google Geocoding response.

        Args:
            data (dict): Response dictionary from Google Geocoding API.

        Returns:
            tuple: (street, suburb, state, postcode)
        """
        if not data or 'results' not in data or len(data['results']) == 0:
            return '', '', '', ''

        components = {}
        for addr_component in data['results'][0]['address_components']:
            for comp_type in addr_component['types']:
                components[comp_type] = addr_component['long_name']

        street_number = components.get('street_number', '')
        street_name = components.get('route', '')
        suburb = components.get('locality', '')
        state = components.get('administrative_area_level_1', 'NSW')
        postcode = components.get('postal_code', '')

        # Format street
        if street_number and street_name:
            street = f"{street_number} {street_name}"
        elif street_name:
            street = street_name
        else:
            street = ''

        return street, suburb, state, postcode

    def get_address(self, longitude: float, latitude: float) -> str:
        """Convert GPS coordinates to a formatted address string.

        Args:
            longitude (float): Longitude coordinate.
            latitude (float): Latitude coordinate.

        Returns:
            str: Formatted address string combining street, suburb, state, and postcode.
                Returns empty string if geocoding fails or coordinates are invalid.
        """
        if self.use_nominatim:
            data = self._reverse_geocode_nominatim(latitude, longitude)
            if data:
                street, suburb, state, postcode = self._extract_address_from_nominatim(data)
                return self._format_address(street, suburb, state, postcode)
        else:
            data = self._reverse_geocode_google(latitude, longitude)
            if data:
                street, suburb, state, postcode = self._extract_address_from_google(data)
                return self._format_address(street, suburb, state, postcode)

        return ''

    @staticmethod
    def _format_address(street: str, suburb: str, state: str, postcode: str) -> str:
        """Format address components into a single string.

        Args:
            street (str): Street address component.
            suburb (str): Suburb/city component.
            state (str): State component.
            postcode (str): Postal code component.

        Returns:
            str: Formatted address string.
        """
        parts = []
        if street:
            parts.append(street)
        if suburb:
            parts.append(suburb)
        if state:
            parts.append(state)
        if postcode:
            parts.append(postcode)

        return ', '.join(parts)
