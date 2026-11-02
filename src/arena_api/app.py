from fastapi import FastAPI, HTTPException

from arena_api.replays import (
    Replay,
    ReplayError,
    ReplaySummary,
    get_replay,
    list_replays,
    logs_dir,
)

app = FastAPI(title="Agent Arena")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/replays")
def replays() -> list[ReplaySummary]:
    return list_replays(logs_dir())


@app.get("/replays/{replay_id}")
def replay(replay_id: str) -> Replay:
    try:
        found = get_replay(logs_dir(), replay_id)
    except ReplayError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if found is None:
        raise HTTPException(status_code=404, detail="replay not found")
    return found
