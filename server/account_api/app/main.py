import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .routers import admin, auth, billing, exports

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Media Studio Account API", version="0.1.0")
app.include_router(auth.router)
app.include_router(auth.me_router)
app.include_router(billing.router)
app.include_router(exports.router)
app.include_router(admin.router)

_ADMIN_STATIC = Path(__file__).resolve().parent / "static"
app.mount("/admin/static", StaticFiles(directory=_ADMIN_STATIC), name="admin-static")


@app.on_event("startup")
def initialize_admin_tables():
    admin.ensure_admin_schema()


@app.get("/admin", include_in_schema=False)
def admin_home():
    return FileResponse(_ADMIN_STATIC / "admin" / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}
