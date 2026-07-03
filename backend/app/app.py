from fastapi import FastAPI

app = FastAPI(title="CitePilot")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "note" : "stub for now"}
