"""
Landsat thermal band (ST_B10) processing for the app3 2D web map.

This does the numeric work only (no folium, no baked HTML map):

  1. Reads the Landsat ST_B10 GeoTIFF and calibrates it to Celsius.
  2. Reprojects its bounds to WGS84 (lat/lon) so the frontend Leaflet
     map can place the overlay correctly on top of a satellite basemap.
  3. Renders a transparent RGBA PNG (fill/invalid pixels = alpha 0,
     valid pixels alpha-scaled by intensity for a "premium" blended
     look instead of a flat, opaque wash).
  4. Writes a small JSON metadata file (bounds + min/max temperature).

FastAPI serves the PNG + JSON as static files; the app3 Leaflet map
(home3.html) draws the PNG with L.imageOverlay(bounds) on top of a
satellite tile layer. This runs once at app startup, not per-request.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional, Union

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import transform_bounds
from PIL import Image
from matplotlib.colors import LinearSegmentedColormap

logger = logging.getLogger(__name__)

# Landsat Collection 2 Level-2 ST_B10 calibration constants
# (see USGS Landsat 8-9 Collection 2 Level-2 Science Product Guide)
ST_MULT = 0.00341802
ST_ADD = 149.0
KELVIN_TO_CELSIUS = 273.15

# Perceptual palettes like inferno/viridis go black -> purple -> yellow,
# which reads as "data / no data" to a general viewer, not "cold / hot" -
# dark pixels look like missing data even when they're the coldest real
# pixels in the scene. A blue-to-red thermal ramp is the universally
# understood convention (weather maps, thermal cameras, HVAC apps), so we
# use one here instead, purely for interpretability.
THERMAL_CMAP = LinearSegmentedColormap.from_list(
    "cold_to_hot",
    [
        (0.00, "#1e3a8a"),  # coldest - deep blue
        (0.22, "#2563eb"),  # blue
        (0.42, "#06b6d4"),  # cyan
        (0.58, "#facc15"),  # yellow
        (0.75, "#f97316"),  # orange
        (1.00, "#dc2626"),  # hottest - red
    ],
)

# Flat overlay opacity for every valid pixel. Earlier versions scaled alpha
# by temperature so cool pixels faded toward the basemap - but that made
# cold areas look like missing data instead of "cold." Hot/cold should be
# told apart by color (the palette above), not by how visible the pixel is,
# so every valid pixel gets the same opacity.
OVERLAY_ALPHA = 0.58

# Where processed assets are written; served by FastAPI as static files.
STATIC_DIR = Path(__file__).resolve().parent / "static"
OVERLAY_PNG = STATIC_DIR / "thermal_overlay.png"
META_JSON = STATIC_DIR / "thermal_meta.json"


class RasterProcessingError(RuntimeError):
    """Raised when the source raster is missing or unusable."""


def _to_celsius(band: np.ndarray) -> np.ndarray:
    kelvin = band.astype("float64") * ST_MULT + ST_ADD
    return kelvin - KELVIN_TO_CELSIUS


def process_landsat_thermal(tiff_path: Union[str, Path], max_dimension: int = 1600) -> dict:
    """
    Read a Landsat ST_B10 GeoTIFF, calibrate to Celsius, and write:
      - STATIC_DIR/thermal_overlay.png  (transparent RGBA, WGS84-aligned)
      - STATIC_DIR/thermal_meta.json    (bounds + temperature stats)

    Returns the metadata dict. Raises RasterProcessingError if the file
    is missing or contains no valid pixels.
    """
    tiff_path = Path(tiff_path)
    if not tiff_path.exists():
        raise RasterProcessingError(f"Thermal band file not found: {tiff_path}")

    STATIC_DIR.mkdir(parents=True, exist_ok=True)

    with rasterio.open(tiff_path) as src:
        src_crs = src.crs
        src_bounds = src.bounds  # left, bottom, right, top, in native CRS

        # Downsample large scenes so the overlay stays light in the browser.
        scale = min(1.0, max_dimension / max(src.width, src.height))
        if scale < 1.0:
            out_shape = (int(src.height * scale), int(src.width * scale))
            band = src.read(1, out_shape=out_shape, resampling=Resampling.average)
        else:
            band = src.read(1)

    celsius = _to_celsius(band)
    valid_mask = band > 0  # Landsat Collection 2 fill value is 0
    celsius = np.where(valid_mask, celsius, np.nan)

    if not np.any(valid_mask):
        raise RasterProcessingError(f"No valid thermal pixels found in {tiff_path.name}")

    vmin = float(np.nanmin(celsius))
    vmax = float(np.nanmax(celsius))

    # transform_bounds densifies the edges internally, which is more
    # accurate than sampling only the 2-4 raster corners by hand.
    min_lon, min_lat, max_lon, max_lat = transform_bounds(src_crs, "EPSG:4326", *src_bounds)

    norm = (celsius - vmin) / (vmax - vmin) if vmax > vmin else np.zeros_like(celsius)
    norm = np.nan_to_num(norm, nan=0.0)
    rgba = THERMAL_CMAP(norm)  # float 0..1, shape (H, W, 4); blue=cold, red=hot

    # Same opacity everywhere valid, so cold areas stay clearly blue instead
    # of fading toward invisible - color alone communicates hot vs cold.
    rgba[..., 3] = OVERLAY_ALPHA
    rgba[~valid_mask, 3] = 0.0  # fully transparent outside valid data

    rgba_uint8 = (rgba * 255).astype("uint8")
    Image.fromarray(rgba_uint8, mode="RGBA").save(OVERLAY_PNG)

    meta = {
        "source_file": tiff_path.name,
        "bounds": {
            "min_lat": min_lat,
            "max_lat": max_lat,
            "min_lon": min_lon,
            "max_lon": max_lon,
        },
        "center": {"lat": (min_lat + max_lat) / 2, "lon": (min_lon + max_lon) / 2},
        "temperature_celsius": {"min": round(vmin, 2), "max": round(vmax, 2)},
        "overlay_image_url": "/app3/static/thermal_overlay.png",
        "valid_pixel_count": int(valid_mask.sum()),
    }
    META_JSON.write_text(json.dumps(meta, indent=2))
    logger.info(
        "app3: processed %s -> %s (%.1f°C to %.1f°C, %d valid px)",
        tiff_path.name, OVERLAY_PNG.name, vmin, vmax, meta["valid_pixel_count"],
    )
    return meta


def load_cached_meta() -> Optional[dict]:
    """Return previously written metadata, if any (used as a fallback)."""
    if META_JSON.exists():
        return json.loads(META_JSON.read_text())
    return None

def sample_temperature(lat: float, lon: float, tiff_path: Path) -> Optional[float]:
    """
    Sample the exact Land Surface Temperature (in Celsius) at a given
    WGS84 lat/lon coordinate directly from the Landsat TIFF.
    Returns None if the point is out of bounds or invalid (fill pixel).
    """
    if not tiff_path.exists():
        return None

    try:
        with rasterio.open(tiff_path) as src:
            # Transform WGS84 (EPSG:4326) to the raster's native CRS
            xs, ys = rasterio.warp.transform("EPSG:4326", src.crs, [lon], [lat])
            
            # Sample the pixel value
            try:
                val = next(src.sample([(xs[0], ys[0])]))[0]
            except IndexError:
                # Out of bounds
                return None
            
            # Landsat Collection 2 Level 2 fill value is 0
            if val <= 0:
                return None
                
            # Calibrate to Celsius using the constants in this module
            celsius = (float(val) * ST_MULT + ST_ADD) - KELVIN_TO_CELSIUS
            return round(celsius, 2)
    except Exception as e:
        logger.error(f"Error sampling temperature at {lat},{lon}: {e}")
        return None