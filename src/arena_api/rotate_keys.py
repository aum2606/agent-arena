"""Move every stored API key to the current secret: `python -m arena_api.rotate_keys`.

Set the new secret in KEY_ENCRYPTION_SECRET and the one being retired in
KEY_ENCRYPTION_OLD_SECRETS first; once this has run, the old one can be dropped (D-078).
"""

from arena_api import store
from arena_api.secret_box import check_secret, reencrypt


def rotate_all() -> int:
    """Re-encrypt every saved key under the current secret; returns how many."""
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT fighter_id, version, api_key_encrypted FROM fighter_versions"
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE fighter_versions SET api_key_encrypted = %s "
                "WHERE fighter_id = %s AND version = %s",
                (reencrypt(row["api_key_encrypted"]), row["fighter_id"], row["version"]),
            )
    return len(rows)


def main() -> None:
    check_secret()
    print(f"re-encrypted {rotate_all()} saved keys under the current secret")


if __name__ == "__main__":
    main()
