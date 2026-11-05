"""Fetch the weather forecast from Open-Meteo (free, no API key needed)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cache

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
# Free services that estimate your location from your internet connection.
LOCATION_URLS = ("https://ipinfo.io/json", "https://ipapi.co/json/")
LOCATION_MAX_AGE = 3 * 60 * 60  # look your location up again after 3 hours

# WMO weather codes used by Open-Meteo.
WEATHER_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    56: "light freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "light freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "heavy showers",
    85: "light snow showers", 86: "snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}


RAIN_MENTION_ABOVE = 20  # percent


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

    @property
    def mention_rain(self) -> bool:
        """Only worth saying when the chance of rain is over 20 percent."""
        return self.rain_chance > RAIN_MENTION_ABOVE

    def spoken(self, period: str) -> str:
        """The sentence she says after the greeting, e.g. "It's 8 degrees."."""
        t = round(self.temperature)
        degrees = f"{'minus ' if t < 0 else ''}{abs(t)} degree{'' if abs(t) == 1 else 's'}"
        text = f"It's {degrees}"
        if self.mention_rain:
            text += f", with a {self.rain_chance} percent chance of rain this {period}"
        return text + "."


@cache  # made once: loading the certificate list takes a few milliseconds each time
def ssl_context():
    """Check HTTPS certificates against certifi's up-to-date list.

    Windows' own certificate list can be out of date, which makes Python
    report "certificate has expired". certifi is the same list the voice
    (edge-tts) uses.
    """
    import ssl

    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def _get_json(url: str, params: dict, timeout: float = 10.0) -> dict:
    # Imported here rather than at the top, as they slow down starting the assistant.
    import ssl
    import urllib.error
    import urllib.parse
    import urllib.request

    request = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(params)}", headers={"User-Agent": "voice-assistant/1.0"}
    )
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


@cache  # a city doesn't move: look it up once
def find_city(city: str) -> tuple[float, float, str]:
    """Return (latitude, longitude, display name) for a city name."""
    results = _get_json(GEOCODE_URL, {"name": city, "count": 1, "language": "en"}).get("results")
    if not results:
        raise ValueError(f"Couldn't find a place called '{city}'")
    return results[0]["latitude"], results[0]["longitude"], results[0]["name"]


_location_cache: dict = {}  # {"value": (lat, lon, city), "at": time.monotonic()}


def detect_location() -> tuple[float, float, str]:
    """Estimate (latitude, longitude, city) from your internet connection.

    Accurate to roughly your city. With a VPN on, it finds the VPN's location.
    The answer is remembered for a few hours, which saves time on each forecast.
    """
    if not _location_cache or time.monotonic() - _location_cache["at"] >= LOCATION_MAX_AGE:
        _location_cache.update(value=_lookup_location(), at=time.monotonic())
    return _location_cache["value"]


def _lookup_location() -> tuple[float, float, str]:
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


def get_weather(city: str = "", units: str = "metric",
                start: datetime | None = None, end: datetime | None = None) -> WeatherReport:
    """Forecast for the hours from ``start`` to ``end`` (default: the next 8 hours).

    Uses ``city``, or your detected location if ``city`` is empty. Times are
    the local time of the place, which is normally your computer's time.
    """
    lat, lon, name = find_city(city) if city.strip() else detect_location()
    imperial = units == "imperial"
    data = _get_json(FORECAST_URL, {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m",  # the latest measured temperature
        "hourly": "temperature_2m,apparent_temperature,weather_code,"
        "precipitation_probability,wind_speed_10m",
        "timezone": "auto",
        "forecast_days": 3,
        "temperature_unit": "fahrenheit" if imperial else "celsius",
        "wind_speed_unit": "mph" if imperial else "kmh",
    })
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    start = max(start or now, now)  # the past isn't worth forecasting
    hours = summarise_hours(data["hourly"], start, end or start + timedelta(hours=8))
    latest = (data.get("current") or {}).get("temperature_2m")
    if latest is not None:
        hours["temperature"] = latest
    return WeatherReport(
        city=name,
        temperature_unit="°F" if imperial else "°C",
        wind_unit="mph" if imperial else "km/h",
        **hours,
    )


def summarise_hours(hourly: dict, start: datetime, end: datetime) -> dict:
    """Boil Open-Meteo's hourly forecast down to one summary for [start, end)."""
    times = [datetime.fromisoformat(t) for t in hourly["time"]]
    picked = [i for i, t in enumerate(times) if start <= t < end]
    if not picked:  # clocks disagree: use the first hours available from start
        picked = [i for i, t in enumerate(times) if t >= start][:8] or list(range(8))

    def values(key):
        return [hourly[key][i] for i in picked if hourly[key][i] is not None]

    codes = values("weather_code")
    # The most common weather; on a tie, the more notable one (higher code).
    code = max(set(codes), key=lambda c: (codes.count(c), c)) if codes else -1
    temps = values("temperature_2m")
    return {
        "description": WEATHER_CODES.get(code, "unsettled weather"),
        "temperature": hourly["temperature_2m"][picked[0]],
        "feels_like": hourly["apparent_temperature"][picked[0]],
        "high": max(temps),
        "low": min(temps),
        "rain_chance": int(max(values("precipitation_probability"), default=0)),
        "wind_speed": max(values("wind_speed_10m")),
    }
