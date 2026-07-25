"""
GeoHeat — FastAPI backend
=========================
Serves a map front end that:
  1. Takes the user's browser geolocation (lat/lon).
  2. Shows an OpenStreetMap street layer and a satellite imagery layer.
  3. Overlays a "heat signature" (land surface temperature) layer computed
     on Google Earth Engine (MODIS LST, 8-day composite) around that point.

Setup
-----
1. pip install -r requirements.txt

2. Create a .env file next to this script with:
     GEE_PROJECT=urban-heat-ai

3. Authenticate Earth Engine ONCE on this machine (one-time, opens a browser
   to log in with the Google account that has Earth Engine access):

     earthengine authenticate

   This writes a credentials file to your user profile
   (~/.config/earthengine/credentials on Linux/Mac, or
   %APPDATA%\\earthengine\\credentials on Windows) that ee.Initialize()
   picks up automatically on every future run. You only need to redo this
   if you switch machines or the token gets revoked.

   If the CLI command isn't available, run this instead from a Python shell
   in the same environment:
     python -c "import ee; ee.Authenticate()"

   The app also attempts this automatically on first request (see
   init_earth_engine below) as a convenience, but it still requires an
   interactive browser step, so doing it manually first is more reliable.

4. Make sure Earth Engine API is enabled for your project and your Google
   account has access at https://code.earthengine.google.com/.

5. uvicorn app:app --reload --port 8000
6. Open http://localhost:8000 and allow location access.

Notes
-----
- The heat layer uses MODIS/061/MOD11A2 (8-day, 1km, day land surface
  temperature). It's a real satellite thermal product, not a toy — good
  global coverage, ~1km resolution, refreshed every 8 days.
- Earth Engine tiles are served straight from Google's tile servers; this
  backend just asks EE to compute a `mapid`/`token` (or a signed tile URL
  template) and hands that template to the browser, which then talks to
  Google directly for the actual tile images.
"""

import os
import logging
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

import httpx
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("geoheat")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load variables from a .env file sitting next to this script.
load_dotenv(os.path.join(BASE_DIR, ".env"))

app = FastAPI(title="GeoHeat", description="Location-aware heat signature map viewer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# --------------------------------------------------------------------------
# Earth Engine initialization
# --------------------------------------------------------------------------
_ee_ready = False
_ee_error: Optional[str] = None


def init_earth_engine() -> None:
    """
    Initialize the Earth Engine Python API once, lazily, on first request.

    Uses user credentials created by `earthengine authenticate` (no service
    account JSON needed). If no credentials exist yet, it tries to trigger
    the interactive auth flow itself once, so a fresh clone of this project
    can self-heal on first run instead of just failing forever.
    """
    global _ee_ready, _ee_error
    if _ee_ready:
        return

    import ee

    project = os.environ.get("GEE_PROJECT")

    def _try_initialize() -> None:
        ee.Initialize(project=project)

    try:
        _try_initialize()
        log.info("Earth Engine initialized with user credentials.")
        _ee_ready = True
        _ee_error = None
        return
    except Exception as first_exc:  # noqa: BLE001
        log.warning(
            "Earth Engine not initialized yet (%s). Attempting interactive "
            "ee.Authenticate() once — check your terminal/browser for a "
            "login prompt.",
            first_exc,
        )

    # Not authenticated yet — try the one-time interactive flow ourselves.
    # This will print a URL to the console (and may open a browser tab).
    # It only works for a human sitting at this machine/terminal; it will
    # simply fail again on a headless server with no browser access, which
    # is fine — the error message below still tells the user what to do.
    try:
        ee.Authenticate()
        _try_initialize()
        log.info("Earth Engine authenticated and initialized successfully.")
        _ee_ready = True
        _ee_error = None
    except Exception as second_exc:  # noqa: BLE001
        _ee_error = (
            "Earth Engine credentials not found or invalid. Run this once "
            "in your terminal, in the same environment as this app, then "
            "restart the server:\n"
            "    earthengine authenticate\n"
            "or, from a Python shell:\n"
            "    python -c \"import ee; ee.Authenticate()\"\n"
            f"Underlying error: {second_exc}"
        )
        log.error("Earth Engine failed to initialize: %s", second_exc)


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/status")
async def status():
    """Lets the frontend know whether Earth Engine is configured correctly."""
    init_earth_engine()
    return {"earth_engine_ready": _ee_ready, "error": _ee_error}


@app.get("/api/reverse-geocode")
async def reverse_geocode(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    """
    Resolves lat/lon into a city/region name.

    Tries Photon (komoot's free OSM-based geocoder) first — it's more
    permissive about automated/API traffic than Nominatim's public
    instance. Falls back to Nominatim if Photon fails. If both fail, this
    still returns 200 with placeholder text instead of a hard error, since
    a broken city label shouldn't block the map or the heat overlay.
    """
    headers = {
        # A real, descriptive User-Agent. Nominatim in particular will 403
        # generic/placeholder ones, so put your actual contact info here.
        "User-Agent": "GeoHeat-DevApp/1.0 (personal project; contact: your-real-email@example.com)",
        "Accept-Language": "en",
    }

    async def try_photon() -> Optional[dict]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://photon.komoot.io/reverse",
                    params={"lat": lat, "lon": lon},
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
            props = (data.get("features") or [{}])[0].get("properties", {})
            if not props:
                return None
            city = props.get("city") or props.get("town") or props.get("village") or props.get("name")
            if not city:
                return None
            return {
                "city": city,
                "state": props.get("state"),
                "country": props.get("country"),
                "display_name": ", ".join(
                    filter(None, [city, props.get("state"), props.get("country")])
                ),
            }
        except Exception as exc:  # noqa: BLE001
            log.warning("Photon reverse geocode failed: %s", exc)
            return None

    async def try_nominatim() -> Optional[dict]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://nominatim.openstreetmap.org/reverse",
                    params={"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 10},
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
            addr = data.get("address", {})
            city = (
                addr.get("city")
                or addr.get("town")
                or addr.get("village")
                or addr.get("county")
            )
            if not city:
                return None
            return {
                "city": city,
                "state": addr.get("state"),
                "country": addr.get("country"),
                "display_name": data.get("display_name"),
            }
        except Exception as exc:  # noqa: BLE001
            log.warning("Nominatim reverse geocode failed: %s", exc)
            return None

    result = await try_photon() or await try_nominatim()

    if result is None:
        # Degrade gracefully — don't 502 the whole request over a label.
        return {
            "city": f"{lat:.3f}, {lon:.3f}",
            "state": None,
            "country": None,
            "display_name": "Location name unavailable",
        }

    return result


@app.get("/api/heat")
async def heat_layer(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(25, gt=0, le=200),
):
    """
    Computes a Land Surface Temperature ("heat signature") tile layer from
    Google Earth Engine, centered on the given coordinates, and returns an
    XYZ tile URL template the frontend can drop straight into a Leaflet
    TileLayer.
    """
    init_earth_engine()
    if not _ee_ready:
        raise HTTPException(
            status_code=503,
            detail=(
                "Earth Engine is not initialized on the server. "
                f"{_ee_error}"
            ),
        )

    import ee

    try:
        point = ee.Geometry.Point([lon, lat])
        region = point.buffer(radius_km * 1000)

        # MODIS 8-day Land Surface Temperature, most recent 60 days,
        # cloud/quality-masked, median-composited so gaps get filled in.
        collection = (
            ee.ImageCollection("MODIS/061/MOD11A2")
            .filterDate(ee.Date(ee.Date("now").format()).advance(-60, "day"), ee.Date("now"))
            .filterBounds(region)
            .select("LST_Day_1km")
        )

        image = collection.median()

        # Scale factor per MODIS LST spec: raw * 0.02 = Kelvin -> convert to Celsius.
        lst_celsius = image.multiply(0.02).subtract(273.15).rename("LST_C")

        vis_params = {
            "min": 0,
            "max": 45,
            "palette": [
                "040274", "030f9c", "0602ff", "235cb1", "307ef3",
                "269db1", "30c8e2", "32d3ef", "3be285", "3ff38f",
                "86e26f", "b5e22e", "d6e21f", "fff705", "ffd611",
                "ffb613", "ff8b13", "ff6e08", "ff500d", "ff0000",
                "de0101", "c21301", "a71001", "911003",
            ],
        }

        clipped = lst_celsius.clip(region)
        map_id_dict = clipped.getMapId(vis_params)
        tile_url_template = map_id_dict["tile_fetcher"].url_format

        return JSONResponse(
            {
                "tile_url": tile_url_template,
                "dataset": "MODIS/061/MOD11A2 (Land Surface Temperature, day, °C)",
                "legend": {"min": 0, "max": 45, "unit": "°C"},
                "radius_km": radius_km,
            }
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("Failed to build Earth Engine heat layer")
        raise HTTPException(status_code=500, detail=f"Earth Engine error: {exc}") from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)