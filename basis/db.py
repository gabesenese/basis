from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from basis.config import settings


@contextmanager
def connect(autocommit: bool = False):
    with psycopg.connect(
        settings.basis_database_url, row_factory=dict_row, autocommit=autocommit
    ) as conn:
        yield conn


def upsert_source(conn, source_id, kind, publisher, redistributable, notes=None):
    conn.execute(
        """
        insert into basis.source (id, kind, publisher, redistributable, notes)
        values (%s, %s, %s, %s, %s)
        on conflict (id) do update
          set kind = excluded.kind,
              publisher = excluded.publisher,
              redistributable = excluded.redistributable,
              notes = excluded.notes
        """,
        (source_id, kind, publisher, redistributable, notes),
    )
