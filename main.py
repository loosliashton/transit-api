from fastapi import FastAPI, HTTPException
from gtfs_service import gtfs_service
import contextlib

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize the GTFS service by loading and caching static data on startup.
    print("Loading static GTFS data...")
    try:
        gtfs_service.load_static_data()
        print("Static data loaded.")
    except Exception as e:
        print(f"Error loading static data: {e}")
    yield
    # Resources are released when the application shuts down.

app = FastAPI(title="Transit API", lifespan=lifespan)

@app.get("/")
def read_root():
    return {"message": "Welcome to the Transit API. Use /departures/{stop_id} to get times."}

@app.get("/stops/search")
def search_stops(name: str) -> list[dict]:
    """
    Search for stops by name (case-insensitive).
    Returns list of matching stops with IDs.
    """
    try:
        return gtfs_service.search_stops(name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/departures/{stop_id}")
def get_departures(stop_id: str) -> dict:
    """
    Get upcoming departures for a specific stop ID.
    Example stop IDs:
    - 18381 (900 East Station - Red Line)
    - 10095 (Washington Blvd)
    """
    try:
        result = gtfs_service.get_departures_for_stop(stop_id)
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
