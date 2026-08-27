import pytest


@pytest.fixture
def db_conn():
    """
    Rolls back at the end so the development database keeps whatever the
    collectors put there. Skips rather than fails when the container is down,
    since the parser tests must stay runnable without it.
    """
    psycopg = pytest.importorskip("psycopg")
    from basis.config import settings

    try:
        conn = psycopg.connect(settings.basis_database_url, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"basis database unavailable: {exc}")

    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
