import secrets
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from basis.api.routes import router
from basis.config import settings

DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

app = FastAPI(title="Basis", docs_url=None, redoc_url=None, openapi_url=None)

"""
A generated secret means restarting the server signs both accounts out. For a
tool with two users that is a fair trade against a secret committed to the
repository, and setting BASIS_SESSION_SECRET makes sessions survive a restart
whenever that becomes annoying.
"""
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.basis_session_secret or secrets.token_hex(32),
    session_cookie="basis_session",
    https_only=False,
    same_site="lax",
    max_age=60 * 60 * 24 * 30,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=DEV_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


def _mount_client() -> None:
    """
    Serves the built client when there is one, so the whole tool runs from a
    single process. In development Vite serves the client instead and talks to
    this over CORS, which is why the origins above exist.
    """
    dist = Path(__file__).resolve().parents[2] / "client" / "dist"
    if not (dist / "index.html").exists():
        return

    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def client(path: str):
        candidate = dist / path
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")


_mount_client()
