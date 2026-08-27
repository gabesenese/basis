import hashlib
import secrets
from dataclasses import dataclass

"""
scrypt from the standard library rather than a hashing dependency. The
parameters are the interactive-login set from RFC 7914, which costs about
100ms and 16MB per attempt. For two accounts that is the whole threat model:
there is no rate limiter to write because there is nobody to rate limit.
"""
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
KEY_BYTES = 32
SALT_BYTES = 16

LANGUAGES = ("pt", "en")


@dataclass(frozen=True)
class Account:
    id: int
    email: str
    display_name: str
    language: str
    timezone: str


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=bytes.fromhex(salt),
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=KEY_BYTES,
    )
    return derived.hex(), salt


def verify_password(password: str, expected_hash: str, salt: str) -> bool:
    candidate, _ = hash_password(password, salt)
    return secrets.compare_digest(candidate, expected_hash)


def generate_password(words: int = 4) -> str:
    """
    Printed once at creation and never recoverable, so it has to be readable
    enough to be moved into a password manager by hand without a typo.
    """
    alphabet = "abcdefghijkmnopqrstuvwxyz23456789"
    return "-".join(
        "".join(secrets.choice(alphabet) for _ in range(5)) for _ in range(words)
    )


def create(conn, email: str, display_name: str, password: str,
           language: str = "pt", timezone: str = "America/Sao_Paulo") -> Account:
    if language not in LANGUAGES:
        raise ValueError(f"language must be one of {LANGUAGES}")

    digest, salt = hash_password(password)
    row = conn.execute(
        """
        insert into basis.account
          (email, display_name, password_hash, password_salt, language, timezone)
        values (%s, %s, %s, %s, %s, %s)
        returning id, email, display_name, language, timezone
        """,
        (email.strip().lower(), display_name, digest, salt, language, timezone),
    ).fetchone()
    return Account(**row)


def set_password(conn, email: str, password: str) -> bool:
    digest, salt = hash_password(password)
    result = conn.execute(
        "update basis.account set password_hash = %s, password_salt = %s where email = %s",
        (digest, salt, email.strip().lower()),
    )
    return result.rowcount > 0


def authenticate(conn, email: str, password: str) -> Account | None:
    """
    A missing account still pays the cost of a hash, so the time taken does not
    say whether the address exists.
    """
    row = conn.execute(
        """
        select id, email, display_name, password_hash, password_salt, language, timezone
        from basis.account where email = %s
        """,
        (email.strip().lower(),),
    ).fetchone()

    if row is None:
        hash_password(password, secrets.token_hex(SALT_BYTES))
        return None

    if not verify_password(password, row["password_hash"], row["password_salt"]):
        return None

    conn.execute(
        "update basis.account set last_seen_at = now() where id = %s", (row["id"],)
    )
    return Account(
        id=row["id"],
        email=row["email"],
        display_name=row["display_name"],
        language=row["language"],
        timezone=row["timezone"],
    )


def by_id(conn, account_id: int) -> Account | None:
    row = conn.execute(
        "select id, email, display_name, language, timezone from basis.account where id = %s",
        (account_id,),
    ).fetchone()
    return None if row is None else Account(**row)


def set_preferences(conn, account_id: int, language: str | None = None,
                    timezone: str | None = None) -> Account | None:
    if language is not None and language not in LANGUAGES:
        raise ValueError(f"language must be one of {LANGUAGES}")

    conn.execute(
        """
        update basis.account
           set language = coalesce(%s, language),
               timezone = coalesce(%s, timezone)
         where id = %s
        """,
        (language, timezone, account_id),
    )
    return by_id(conn, account_id)


def listing(conn) -> list[Account]:
    rows = conn.execute(
        "select id, email, display_name, language, timezone from basis.account order by id"
    ).fetchall()
    return [Account(**row) for row in rows]
