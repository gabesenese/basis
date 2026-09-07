import secrets
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from basis.api.equities import router as equities_router
from basis.api.routes import router
from basis.config import settings

DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

app = FastAPI(title="Basis", docs_url=None, redoc_url=None, openapi_url=None)

def _session_secret() -> str:
    """
    The key that signs session cookies, kept across restarts.

    Generating one at boot was the earlier trade, and it cost more than it was
    worth: every restart invalidated every cookie, so anyone reading the running
    app was signed out each time the server was touched. Editing a file that
    someone is looking at should not end their session.

    So it is generated once and kept in var/, which is outside the repository
    and never committed. BASIS_SESSION_SECRET still wins when it is set, and
    deleting the file is how you deliberately sign everyone out.
    """
    if settings.basis_session_secret:
        return settings.basis_session_secret

    kept = Path(settings.basis_var_root) / "session.key"
    if kept.exists():
        stored = kept.read_text(encoding="utf-8").strip()
        if stored:
            return stored

    minted = secrets.token_hex(32)
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(minted, encoding="utf-8")
    return minted


app.add_middleware(
    SessionMiddleware,
    secret_key=_session_secret(),
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
app.include_router(equities_router)


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
