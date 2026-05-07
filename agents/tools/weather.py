import os
from datetime import datetime, timedelta, timezone
from helpers.utils import get_logger, get_today_date_str
import httpx
from typing import Optional
from pydantic_ai import ModelRetry, UnexpectedModelBehavior
from dotenv import load_dotenv

load_dotenv()
logger = get_logger(__name__)

# -----------------------
# Weather Code Mapping
# -----------------------

def weather_code_to_text(code: Optional[int]) -> str:
    """Map Open-Meteo WMO weather code to a human-readable description."""
    if code is None:
        return "Unknown"
    mapping = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Depositing rime fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        56: "Light freezing drizzle",
        57: "Dense freezing drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        66: "Light freezing rain",
        67: "Heavy freezing rain",
        71: "Slight snow fall",
        73: "Moderate snow fall",
        75: "Heavy snow fall",
        77: "Snow grains",
        80: "Slight rain showers",
        81: "Moderate rain showers",
        82: "Violent rain showers",
        85: "Slight snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with slight hail",
        99: "Thunderstorm with heavy hail",
    }
    return mapping.get(code, "Unknown")


# -----------------------
# Response Formatting
# -----------------------

def _format_weather_response(
    data: dict,
    location_name: str,
    response_type: str = "forecast"
) -> str:
    """Format Open-Meteo JSON response into a readable string for the LLM."""
    lines = []
    today_str = get_today_date_str()

    if response_type == "historical":
        lines.append(f"**Weather Historical Data** [Today's Date: {today_str}]")
    else:
        lines.append(f"**Weather Forecast Data** [Today's Date: {today_str}]")

    lat = data.get("latitude")
    lon = data.get("longitude")
    lines.append(f"Location: {location_name} (Latitude: {lat}, Longitude: {lon})")
    lines.append("")

    # Current weather (forecast only)
    current = data.get("current_weather")
    if current and response_type == "forecast":
        temp = current.get("temperature")
        wind = current.get("windspeed")
        wind_dir = current.get("winddirection")
        code = current.get("weathercode")
        desc = weather_code_to_text(code)

        lines.append("Current Weather:")
        lines.append(f"  - Temperature: {temp}°C")
        lines.append(f"  - Wind Speed: {wind} km/h")
        lines.append(f"  - Wind Direction: {wind_dir}°")
        lines.append(f"  - Condition: {desc}")
        lines.append("")

    # Hourly forecast (next 5 hours, forecast only)
    hourly = data.get("hourly")
    if hourly and response_type == "forecast":
        times = hourly.get("time", [])[:5]
        temps = hourly.get("temperature_2m", [])[:5]
        precips = hourly.get("precipitation", [])[:5]
        codes = hourly.get("weathercode", [])[:5]

        if times:
            lines.append("Next Hours:")
            for t, temp, precip, code in zip(times, temps, precips, codes):
                try:
                    dt = datetime.fromisoformat(t)
                    time_str = dt.strftime("%H:%M")
                except (ValueError, TypeError):
                    time_str = str(t)

                desc = weather_code_to_text(code)
                lines.append(
                    f"  - {time_str}: {temp}°C, {precip}mm rain, {desc}"
                )
            lines.append("")

    # Daily data
    daily = data.get("daily")
    if daily:
        times = daily.get("time", [])
        max_temps = daily.get("temperature_2m_max", [])
        min_temps = daily.get("temperature_2m_min", [])
        precips = daily.get("precipitation_sum", [])
        codes = daily.get("weathercode", [])

        if times:
            if response_type == "historical":
                lines.append("Historical Daily Data:")
            else:
                lines.append("Daily Forecast:")

            for t, tmax, tmin, precip, code in zip(
                times, max_temps, min_temps, precips, codes
            ):
                desc = weather_code_to_text(code)
                lines.append(
                    f"  - {t}: Max {tmax}°C, Min {tmin}°C, "
                    f"Rain {precip}mm, {desc}"
                )

    return "\n".join(lines)


# -----------------------
# Weather Forecast
# -----------------------

async def weather_forecast(latitude: float, longitude: float, days: int = 5) -> str:
    """Get Weather forecast for a specific location.

    Args:
        latitude (float): Latitude of the location
        longitude (float): Longitude of the location
        days (int): Number of days for weather forecast (defaults to 5)

    Returns:
        str: The weather forecast for the specific location
    """
    try:
        base_url = os.getenv(
            "OPEN_METEO_FORECAST_URL",
            "https://api.open-meteo.com/v1/forecast"
        )
        url = (
            f"{base_url}?"
            f"latitude={latitude}&longitude={longitude}"
            "&current_weather=true"
            "&hourly=temperature_2m,precipitation,weathercode"
            "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode"
            "&timezone=auto"
        )

        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=15.0)

        if response.status_code != 200:
            logger.error(
                f"Weather API returned status code {response.status_code}"
            )
            return "Weather service unavailable. Retrying"

        data = response.json()

        if data.get("error"):
            logger.error(
                f"Weather API error: {data.get('reason', 'Unknown')}"
            )
            return "Weather service unavailable. Retrying"

        location_name = f"{latitude}, {longitude}"
        return _format_weather_response(
            data, location_name, response_type="forecast"
        )

    except httpx.TimeoutException:
        logger.error("Weather API request timed out")
        return "Weather request timed out."
    except httpx.RequestError as e:
        logger.error(f"Weather API request failed: {e}")
        return f"Weather request failed: {str(e)}"
    except UnexpectedModelBehavior:
        logger.warning("Weather request exceeded retry limit")
        return "Weather data is temporarily unavailable. Please try again later."
    except Exception as e:
        logger.error(f"Error getting weather forecast: {e}")
        raise ModelRetry(
            f"Unexpected error in weather forecast. {str(e)}"
        )


# -----------------------
# Weather Historical
# -----------------------

async def weather_historical(
    latitude: float, longitude: float, days: int = 5
) -> str:
    """Get historical weather data for a specific location.

    Args:
        latitude (float): Latitude of the location
        longitude (float): Longitude of the location
        days (int): Number of days for weather history (defaults to 5)

    Returns:
        str: The historical weather data for the specific location
    """
    try:
        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=days)

        base_url = os.getenv(
            "OPEN_METEO_ARCHIVE_URL",
            "https://archive-api.open-meteo.com/v1/archive"
        )
        url = (
            f"{base_url}?"
            f"latitude={latitude}&longitude={longitude}"
            f"&start_date={start_date}&end_date={end_date}"
            "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode"
            "&timezone=auto"
        )

        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=15.0)

        if response.status_code != 200:
            logger.error(
                f"Weather API returned status code {response.status_code}"
            )
            return "Weather service unavailable. Retrying"

        data = response.json()

        if data.get("error"):
            logger.error(
                f"Weather API error: {data.get('reason', 'Unknown')}"
            )
            return "Weather service unavailable. Retrying"

        location_name = f"{latitude}, {longitude}"
        return _format_weather_response(
            data, location_name, response_type="historical"
        )

    except httpx.TimeoutException:
        logger.error("Weather API request timed out")
        return "Weather request timed out."
    except httpx.RequestError as e:
        logger.error(f"Weather API request failed: {e}")
        return f"Weather request failed: {str(e)}"
    except UnexpectedModelBehavior:
        logger.warning("Weather request exceeded retry limit")
        return "Weather data is temporarily unavailable. Please try again later."
    except Exception as e:
        logger.error(f"Error getting weather historical data: {e}")
        raise ModelRetry(
            f"Unexpected error in weather historical data. {str(e)}"
        )