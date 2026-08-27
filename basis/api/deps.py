import time
from typing import Callable

from fastapi import HTTPException, Request

from basis import accounts, db

SESSION_KEY = "account_id"


def connection():
    with db.connect() as conn:
        yield conn


def current_account(request: Request):
    account_id = request.session.get(SESSION_KEY)
    if account_id is None:
        raise HTTPException(status_code=401, detail="not signed in")

    with db.connect() as conn:
        account = accounts.by_id(conn, account_id)

    if account is None:
        request.session.clear()
        raise HTTPException(status_code=401, detail="not signed in")
    return account


class Cached:
    """
    The event study rebuilds from about two hundred queries, which is fine once
    and wasteful on every page view. The underlying facts change when a
    collector runs, at most daily, so a short lease costs nothing in freshness
    and takes the rebuild off the request path.
    """

    def __init__(self, produce: Callable, lease_seconds: int = 300):
        self.produce = produce
        self.lease_seconds = lease_seconds
        self.value = None
        self.stamped = 0.0

    def __call__(self, *args):
        now = time.monotonic()
        if self.value is None or now - self.stamped > self.lease_seconds:
            self.value = self.produce(*args)
            self.stamped = now
        return self.value

    def clear(self) -> None:
        self.value = None
        self.stamped = 0.0
