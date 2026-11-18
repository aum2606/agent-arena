"""Apply the database migrations once and exit: `python -m arena_api.migrate`.

A deployment runs this as the database's owner before the API and the worker start, so those two can
connect as a role that cannot change the schema (D-079).
"""

from arena_api.db import migrate

if __name__ == "__main__":
    migrate()
    print("database is up to date")
