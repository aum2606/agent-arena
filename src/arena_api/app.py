from fastapi import FastAPI

app = FastAPI(title="Agent Arena")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
