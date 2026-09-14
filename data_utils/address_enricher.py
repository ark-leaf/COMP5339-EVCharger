"""Address enrichment using free APIs (OpenStreetMap Nominatim and Google Geocoding)."""
import time
import requests
import pandas as pd
from typing import Optional, Tuple
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AddressEnricher:
    """Enrich non-detailed addresses using free geocoding APIs."""

    # OpenStreetMap Nominatim (free, no API key needed)
    NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
    NOMINATIM_HEADERS = {
        'User-Agent': 'NSW-EV-Charging-Data-Enrichment/1.0 (arkcj.leaf@gmail.com)'
    }

    # Google Geocoding API (free tier: 25,000 requests/day)
    GOOGLE_GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"

    def __init__(self, use_nominatim: bool = True, google_api_key: Optional[str] = None):
        """Initialize enricher with preferred API.

        Args:
            use_nominatim: If True, use OpenStreetMap Nominatim (recommended, free)
            google_api_key: Google API key for Google Geocoding API (optional)
        """
        self.use_nominatim = use_nominatim
        self.google_api_key = google_api_key
        self.request_count = 0
        self.last_request_time = 0

    def reverse_geocode_nominatim(self, latitude: float, longitude: float) -> Optional[dict]:
        """Reverse geocode using OpenStreetMap Nominatim.

        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate

        Returns:
            Dictionary with address details or None if request fails

        Note:
            - Free service, no API key required
            - Rate limit: 1 request per second (enforced here)
            - Returns detailed address information
        """
        # Enforce rate limit: 1 request per second for Nominatim
        time_since_last = time.time() - self.last_request_time
        if time_since_last < 1.0:
            time.sleep(1.0 - time_since_last)

        try:
            params = {
                'lat': latitude,
                'lon': longitude,
                'format': 'json',
                'zoom': 18,  # Get most detailed address
                'addressdetails': 1
            }

            response = requests.get(
                self.NOMINATIM_URL,
                params=params,
                headers=self.NOMINATIM_HEADERS,
                timeout=10
            )
            self.last_request_time = time.time()
            self.request_count += 1

            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"Nominatim API error: {response.status_code}")
                return None

        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {e}")
            return None

    def reverse_geocode_google(self, latitude: float, longitude: float) -> Optional[dict]:
        """Reverse geocode using Google Geocoding API.

        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate

        Returns:
            Dictionary with address details or None if request fails

        Note:
            - Requires API key (set GOOGLE_MAPS_API_KEY environment variable)
            - Free tier: 25,000 requests/day
            - Requires billing account even for free tier
        """
        if not self.google_api_key:
            logger.error("Google API key not provided")
            return None

        try:
            params = {
                'latlng': f'{latitude},{longitude}',
                'key': self.google_api_key
            }

            response = requests.get(self.GOOGLE_GEOCODING_URL, params=params, timeout=10)
            self.request_count += 1

            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"Google API error: {response.status_code}")
                return None

        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {e}")
            return None

    def extract_address_from_nominatim(self, data: dict) -> Tuple[str, str, str, str]:
        """Extract address components from Nominatim response.

        Args:
            data: Response dictionary from Nominatim

        Returns:
            Tuple of (street, suburb, state, postcode)
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

    def extract_address_from_google(self, data: dict) -> Tuple[str, str, str, str]:
        """Extract address components from Google response.

        Args:
            data: Response dictionary from Google Geocoding API

        Returns:
            Tuple of (street, suburb, state, postcode)
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

    def enrich_address(self, latitude: float, longitude: float) -> Tuple[str, str, str, str]:
        """Enrich address using coordinates.

        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate

        Returns:
            Tuple of (street, suburb, state, postcode)
        """
        if self.use_nominatim:
            data = self.reverse_geocode_nominatim(latitude, longitude)
            if data:
                return self.extract_address_from_nominatim(data)
        else:
            data = self.reverse_geocode_google(latitude, longitude)
            if data:
                return self.extract_address_from_google(data)

        return '', '', '', ''

    def enrich_dataframe(self, df: pd.DataFrame, lat_col: str = 'Latitude',
                        lon_col: str = 'Longitude') -> pd.DataFrame:
        """Enrich all non-detailed addresses in a DataFrame.

        Args:
            df: DataFrame with lat/lon columns
            lat_col: Name of latitude column
            lon_col: Name of longitude column

        Returns:
            DataFrame with new columns: enriched_street, enriched_suburb,
            enriched_state, enriched_postcode
        """
        results = []

        for idx, row in df.iterrows():
            if pd.isna(row[lat_col]) or pd.isna(row[lon_col]):
                results.append(('', '', '', ''))
                continue

            street, suburb, state, postcode = self.enrich_address(
                row[lat_col],
                row[lon_col]
            )
            results.append((street, suburb, state, postcode))

            if (idx + 1) % 50 == 0:
                logger.info(f"Enriched {idx + 1}/{len(df)} addresses")

        df['enriched_street'] = [r[0] for r in results]
        df['enriched_suburb'] = [r[1] for r in results]
        df['enriched_state'] = [r[2] for r in results]
        df['enriched_postcode'] = [r[3] for r in results]

        logger.info(f"Total API requests: {self.request_count}")

        return df
