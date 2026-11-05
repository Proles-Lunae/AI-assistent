"""Fetch the current weather from Open-Meteo (free, no API key needed)."""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
# Free services that estimate your location from your internet connection.
LOCATION_URLS = ("https://ipinfo.io/json", "https://ipapi.co/json/")

# WMO weather codes used by Open-Meteo.
WEATHER_CODES = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "freezing fog",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    56: "light freezing drizzle",
    57: "freezing drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "freezing rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow grains",
    80: "light showers",
    81: "showers",
    82: "heavy showers",
    85: "light snow showers",
    86: "snow showers",
    95: "thunderstorm",
    96: "thunderstorm with hail",
    99: "thunderstorm with heavy hail",
}


@dataclass
class WeatherReport:
    city: str
    description: str
    temperature: float
    feels_like: float
    high: float
    low: float
    rain_chance: int  # percent
    wind_speed: float
    temperature_unit: str
    wind_unit: str

    def as_dict(self) -> dict:
        data = asdict(self)
        # Whole numbers read aloud better than "7 and a half degrees".
        for key in ("temperature", "feels_like", "high", "low", "wind_speed"):
            data[key] = round(data[key])
        return data

    def summary(self) -> str:
        """A one-sentence spoken summary, used when Claude isn't available."""
        return (
            f"In {self.city} it's {self.description} and {round(self.temperature)} "
            f"degrees, with a high of {round(self.high)}, a low of {round(self.low)} "
            f"and a {self.rain_chance} percent chance of rain."
        )


def ssl_context() -> ssl.SSLContext:
    """Check HTTPS certificates against certifi's up-to-date list.

    Windows' own certificate list can be out of date, which makes Python
    report "certificate has expired". certifi is the same list the voice
    (edge-tts) uses.
    """
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def _get_json(url: str, params: dict, timeout: float = 10.0) -> dict:
    full_url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(full_url, headers={"User-Agent": "voice-assistant/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
            return json.load(response)
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            raise ConnectionError(
                f"secure connection to the weather service failed ({exc.reason.verify_message}). "
                "Check that your computer's date and time are correct; antivirus "
                "'HTTPS scanning' or a company network can also cause this."
            ) from exc
        raise


def find_city(city: str) -> tuple[float, float, str]:
    """Return (latitude, longitude, display name) for a city name."""
    data = _get_json(GEOCODE_URL, {"name": city, "count": 1, "language": "en"})
    results = data.get("results") or []
    if not results:
        raise ValueError(f"Couldn't find a place called '{city}'")
    place = results[0]
    return place["latitude"], place["longitude"], place["name"]


def detect_location() -> tuple[float, float, str]:
    """Estimate (latitude, longitude, city) from your internet connection.

    Accurate to roughly your city. With a VPN on, it finds the VPN's location.
    """
    problems = []
    for url in LOCATION_URLS:
        try:
            data = _get_json(url, {})
            if "loc" in data:  # ipinfo.io: "52.52,13.40"
                lat, lon = (float(x) for x in data["loc"].split(","))
            else:  # ipapi.co
                lat, lon = float(data["latitude"]), float(data["longitude"])
            return lat, lon, data.get("city") or "your area"
        except Exception as exc:
            problems.append(f"{url}: {exc}")
    raise ConnectionError("couldn't work out your location (" + "; ".join(problems) + ")")


def get_weather(city: str = "", units: str = "metric") -> WeatherReport:
    """Weather for ``city``, or for your detected location if ``city`` is empty."""
    lat, lon, name = find_city(city) if city.strip() else detect_location()
    imperial = units == "imperial"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "auto",
        "forecast_days": 1,
        "temperature_unit": "fahrenheit" if imperial else "celsius",
        "wind_speed_unit": "mph" if imperial else "kmh",
    }
    data = _get_json(FORECAST_URL, params)
    current = data["current"]
    daily = data["daily"]
    return WeatherReport(
        city=name,
        description=WEATHER_CODES.get(current["weather_code"], "unsettled weather"),
        temperature=current["temperature_2m"],
        feels_like=current["apparent_temperature"],
        high=daily["temperature_2m_max"][0],
        low=daily["temperature_2m_min"][0],
        rain_chance=int(daily["precipitation_probability_max"][0] or 0),
        wind_speed=current["wind_speed_10m"],
        temperature_unit="°F" if imperial else "°C",
        wind_unit="mph" if imperial else "km/h",
    )
