"""Push a batch of readings to the app / Supabase. Table is only cleared on confirmed success."""

import sqlite3


def send_batch(readings: list[sqlite3.Row]) -> bool:
    """Return True once the receiving end has acknowledged the batch.

    TODO: actual transport — Supabase client insert, and/or whatever channel the app listens on.
    """
    if not readings:
        return True
    raise NotImplementedError
