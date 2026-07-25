import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("app")

from .app1.routes import router as app1_router
from .app2.routes import router as app2_router
from .app3.routes import router as app3_router, process_thermal_data_on_startup
from .app3.raster_processing import STATIC_DIR as APP3_STATIC_DIR
from .app4.routes import router as app4_router
from .app2.sessions import get_current_user_email

app = FastAPI()

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # Protect all routes except app2 (auth) and static files
    if not path.startswith("/app2/") and not path.startswith("/app3/static/"):
        if get_current_user_email(request) is None:
            return RedirectResponse(url="/app2/login")
    return await call_next(request)

# Include routers
app.include_router(app1_router, prefix="/app1")
app.include_router(app2_router, prefix="/app2")
app.include_router(app3_router, prefix="/app3")
app.include_router(app4_router, prefix="/app4")

# Serve the PNG overlay + JSON metadata that app3's raster processing
# step generates (created fresh on every app startup, see below).
APP3_STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/app3/static", StaticFiles(directory=str(APP3_STATIC_DIR)), name="app3-static")


@app.on_event("startup")
async def on_startup():
    # Process the Landsat thermal GeoTIFF exactly once, at boot, so the
    # /app3 map has its overlay ready before the first request arrives.
    # Any failure here is logged, not fatal - app3 will render its
    # "no data loaded" empty state instead of crashing the whole app.
    try:
        await process_thermal_data_on_startup()
    except Exception:
        logger.exception("app3 startup: unexpected error during thermal processing")


@app.get("/")
def root():
    return RedirectResponse(url="/app1/")