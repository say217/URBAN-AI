import base64
import io
import logging
import os
import re
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .raster_processing import (
    STATIC_DIR,
    process_landsat_thermal,
    load_cached_meta,
    RasterProcessingError,
    sample_temperature,
)

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_THERMAL_TIFF_RELATIVE_PATH = Path(
    ".Data/Data/Data/LC08_L2SP_139044_20260601_20260612_02_T1_ST_B10.tiff"
)

# Where tiles drawn with the map's pen tool get saved. Created lazily the
# first time someone actually saves a tile, so it never clutters a fresh
# checkout of the project.
MAP_IMAGE_DIR = PROJECT_ROOT / ".map_image"

# Alternate filename casings/extensions to try if the exact path from the
# env var doesn't exist. Landsat downloads commonly ship as .TIF, and the
# folders/case can vary depending on how the dataset was unzipped.
_ALT_SUFFIXES = [".tiff", ".TIF", ".tif", ".TIFF"]


def _normalize_env_path(raw: str) -> Path:
    """
    .env files are plain text - Windows-style paths pasted in directly
    (e.g. ``.Data\\Data\\Data\\file.tiff``) are NOT automatically turned
    into real path separators on Linux/macOS, so ``Path()`` would treat
    the whole string as one literal folder name containing backslashes.

    This normalizes a path coming from an environment variable so it
    works regardless of which OS wrote the .env file:
      1. Convert backslashes to the platform separator.
      2. Collapse a leading "." that isn't followed by a slash (a common
         paste artifact of ``.\\Data\\...`` becoming ``.Data\\...``)
         back into "./".
    """
    raw = raw.strip().strip('"').strip("'")

    # ".Data\Data\..."  ->  "./Data/Data/..."
    if raw.startswith(".") and len(raw) > 1 and raw[1] not in ("/", "\\", "."):
        raw = "./" + raw[1:]

    # Treat it as a Windows-style path first (handles backslashes cleanly),
    # then rebuild as a normal Path so it works on any OS.
    parts = PureWindowsPath(raw).parts
    return Path(*parts) if parts else Path(raw)


def _find_existing_variant(candidate: Path) -> Optional[Path]:
    """Try the exact candidate, then common suffix/case variants."""
    if candidate.exists():
        return candidate
    stem_path = candidate.with_suffix("")
    for suffix in _ALT_SUFFIXES:
        alt = stem_path.with_suffix(suffix)
        if alt.exists():
            return alt
    return None


def resolve_thermal_tiff_path() -> Optional[Path]:
    """Resolve the Landsat thermal band path from env or the project tree."""
    configured_raw = os.getenv("APP3_THERMAL_TIFF_PATH") or os.getenv("LANDSAT_B10_PATH")

    if configured_raw:
        normalized = _normalize_env_path(configured_raw)
        candidate = normalized if normalized.is_absolute() else (PROJECT_ROOT / normalized)
        found = _find_existing_variant(candidate)
        if found:
            return found
        logger.warning(
            "app3 startup: LANDSAT_B10_PATH/APP3_THERMAL_TIFF_PATH was set to %r "
            "(resolved to %s) but no matching file was found there, including "
            "common suffix variants %s.",
            configured_raw, candidate, _ALT_SUFFIXES,
        )
        # Fall through to the default candidates below instead of giving up,
        # in case the env var is stale but the default file is present.

    for suffix in [""] + _ALT_SUFFIXES:
        candidate = (
            PROJECT_ROOT / DEFAULT_THERMAL_TIFF_RELATIVE_PATH
            if suffix == ""
            else PROJECT_ROOT / DEFAULT_THERMAL_TIFF_RELATIVE_PATH.with_suffix(suffix)
        )
        if candidate.exists():
            return candidate
    return None


_thermal_meta: Optional[dict] = None


def get_thermal_meta() -> Optional[dict]:
    return _thermal_meta


async def process_thermal_data_on_startup() -> None:
    """
    Runs once when the FastAPI app boots (wired up in main.py's startup
    event). Converts the Landsat GeoTIFF into a static PNG overlay +
    JSON metadata up front, so every request to /app3 is instant - no
    raster work happens per-request.
    """
    global _thermal_meta
    try:
        thermal_tiff_path = resolve_thermal_tiff_path()
        if thermal_tiff_path is None:
            logger.warning(
                "app3 startup: no Landsat thermal file found. Set "
                "APP3_THERMAL_TIFF_PATH or LANDSAT_B10_PATH in .env to a "
                "project-relative path (forward slashes recommended), e.g. "
                "LANDSAT_B10_PATH=Data/Data/Data/LC08_L2SP_139044_20260601_20260612_02_T1_ST_B10.tiff"
            )
            _thermal_meta = load_cached_meta()
            return

        logger.info("app3 startup: processing thermal raster at %s", thermal_tiff_path)
        _thermal_meta = process_landsat_thermal(thermal_tiff_path)
    except RasterProcessingError as exc:
        logger.error("app3 startup: thermal processing failed: %s", exc)
        _thermal_meta = load_cached_meta()  # fall back to the last good run, if any


@router.get("/")
def home(request: Request):
    meta = _thermal_meta or load_cached_meta()
    return templates.TemplateResponse(
        "home3.html",
        {"request": request, "thermal_meta": meta},
    )

@router.get("/inspect")
def inspect(lat: float, lon: float):
    tiff_path = resolve_thermal_tiff_path()
    if not tiff_path:
        return {"lst_celsius": None}
    
    lst = sample_temperature(lat, lon, tiff_path)
    return {"lst_celsius": lst}


# ---------------------------------------------------------------------------
# Chat endpoint
#
# Powers the chat panel in home3.html. If ANTHROPIC_API_KEY is set in the
# environment, questions are answered by Claude with the scene's processed
# metadata (bounds, min/max temp, etc.) given as context. Otherwise it falls
# back to simple rule-based answers derived straight from that metadata, so
# the panel is still useful with zero extra setup.
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []


class ChatResponse(BaseModel):
    reply: str


def _rule_based_reply(message: str, meta: Optional[dict]) -> str:
    if not meta:
        return (
            "No thermal scene is loaded yet, so I don't have data to talk about. "
            "Set LANDSAT_B10_PATH in .env and restart the server."
        )

    text = message.lower()
    temp = meta["temperature_celsius"]
    bounds = meta["bounds"]

    if any(k in text for k in ["max", "hottest", "highest"]):
        return f"The hottest surface temperature in this scene is {temp['max']}°C."
    if any(k in text for k in ["min", "coldest", "lowest"]):
        return f"The coolest surface temperature in this scene is {temp['min']}°C."
    if any(k in text for k in ["bound", "extent", "area", "cover"]):
        return (
            f"This scene covers latitude {bounds['min_lat']:.4f} to {bounds['max_lat']:.4f} "
            f"and longitude {bounds['min_lon']:.4f} to {bounds['max_lon']:.4f}."
        )
    if any(k in text for k in ["pixel", "valid", "resolution"]):
        return f"There are {meta['valid_pixel_count']:,} valid thermal pixels in this scene."
    if any(k in text for k in ["file", "source", "scene"]):
        return f"This dashboard is showing {meta['source_file']}."

    return (
        f"This scene ({meta['source_file']}) ranges from {temp['min']}°C to {temp['max']}°C "
        f"across {meta['valid_pixel_count']:,} valid pixels. Ask me about the min/max "
        f"temperature, the coverage area, or the source file."
    )


def _try_claude_reply(message: str, history: List[ChatMessage], meta: Optional[dict]) -> Optional[str]:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
    except ImportError:
        logger.warning("ANTHROPIC_API_KEY is set but the 'anthropic' package isn't installed.")
        return None

    system = (
        "You are a concise data assistant embedded in a thermal-imaging dashboard. "
        "Answer questions about the currently loaded Landsat land-surface-temperature "
        "scene using only the metadata provided. Keep answers to 1-3 sentences."
    )
    context = f"Scene metadata (JSON): {meta}" if meta else "No scene is currently loaded."

    try:
        client = anthropic.Anthropic(api_key=api_key)
        messages = [{"role": h.role, "content": h.content} for h in history[-10:]]
        messages.append({"role": "user", "content": f"{context}\n\nQuestion: {message}"})
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            system=system,
            messages=messages,
        )
        parts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
        return "\n".join(parts).strip() or None
    except Exception:
        logger.exception("app3 chat: Claude call failed, falling back to rule-based reply")
        return None


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    meta = _thermal_meta or load_cached_meta()
    reply = _try_claude_reply(request.message, request.history, meta)
    if reply is None:
        reply = _rule_based_reply(request.message, meta)
    return ChatResponse(reply=reply)

from .ai_config import stream_chat_response

@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    meta = _thermal_meta or load_cached_meta()
    
    async def generate():
        try:
            async for chunk in stream_chat_response(request.message, request.history, meta):
                yield chunk
        except Exception as e:
            yield f"Error: {str(e)}"

    return StreamingResponse(generate(), media_type="text/plain")

# ---------------------------------------------------------------------------
# Map draw-and-save endpoint
#
# Powers the pen tool on the map in home3.html. The client draws a
# rectangle over any part of the map, captures that region as a PNG in
# the browser (html2canvas), and posts it here as a base64 data URL. This
# handler decodes it, pads/crops it onto a square canvas so every saved
# file is a clean tile, and writes it into the project-root ".map_image"
# folder (created automatically on first save).
# ---------------------------------------------------------------------------

try:
    from PIL import Image
except ImportError:  # Pillow should already be available for PNG overlay generation
    Image = None

_DATA_URL_RE = re.compile(r"^data:image/(png|jpeg|jpg);base64,(.+)$", re.DOTALL)


class SaveMapImageRequest(BaseModel):
    image: str  # base64 data URL, e.g. "data:image/png;base64,...."


class SaveMapImageResponse(BaseModel):
    success: bool
    filename: Optional[str] = None
    path: Optional[str] = None
    error: Optional[str] = None


@router.post("/save-map-image", response_model=SaveMapImageResponse)
def save_map_image(request: SaveMapImageRequest):
    if Image is None:
        return SaveMapImageResponse(
            success=False, error="Pillow (PIL) is not installed on the server."
        )

    match = _DATA_URL_RE.match(request.image.strip())
    if not match:
        return SaveMapImageResponse(
            success=False, error="Expected a base64 PNG/JPEG data URL."
        )

    try:
        raw = base64.b64decode(match.group(2))
        img = Image.open(io.BytesIO(raw))
        img.load()
        img = img.convert("RGBA")
    except Exception as exc:
        logger.warning("save_map_image: could not decode uploaded image: %s", exc)
        return SaveMapImageResponse(success=False, error="Could not decode the uploaded image.")

    # Enforce a clean square tile regardless of what the client sent, so
    # every file in .map_image is uniform (pad, don't stretch/crop content).
    side = max(img.width, img.height)
    square = Image.new("RGBA", (side, side), (11, 11, 15, 255))
    square.paste(img, ((side - img.width) // 2, (side - img.height) // 2), img)

    try:
        MAP_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"tile_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
        out_path = MAP_IMAGE_DIR / filename
        square.save(out_path, format="PNG")
    except OSError as exc:
        logger.error("save_map_image: failed to write tile to disk: %s", exc)
        return SaveMapImageResponse(success=False, error="Could not write the tile to disk.")

    logger.info("save_map_image: saved drawn map section to %s", out_path)
    return SaveMapImageResponse(
        success=True,
        filename=filename,
        path=str(out_path.relative_to(PROJECT_ROOT)),
    )