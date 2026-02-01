# UTA Realtime Transit API

A lightweight Python API using FastAPI to serve realtime departure boards for Utah Transit Authority (UTA) stops.

## Features

- **Realtime Data**: Fetches live Trip Updates from UTA's GTFS-Realtime feed.
- **Auto-Matching**: Automatically correlates live trip IDs with static schedules to provide Route Names and Headsigns.
- **Search**: Integrated stop search endpoint.

## Setup

### Running with Docker (Recommended)

1.  **Build the Image**:

    ```bash
    docker build -t transit-api .
    ```

2.  **Run the Container**:

    ```bash
    docker run -p 8000:8000 transit-api
    ```

3.  Access at `http://localhost:8000`.

### Running with Docker Compose

1.  **Start the Service**:

    ```bash
    docker-compose up -d
    ```

2.  **Stop the Service**:

    ```bash
    docker-compose down
    ```

### Manual Setup

1. **Install Dependencies**

   ```bash
   pip install -r requirements.txt
   ```

2. **Run the Server**
   ```bash
   python -m uvicorn main:app --reload
   ```

## Usage

### Search for a Stop

```http
GET /stops/search?name=State
```

### Get Departures

```http
GET /departures/{stop_id}
```

Example: `/departures/18382` (Red Line - 900 East, toward University Medical)

## Technology

- **FastAPI**: High-performance web framework.
- **GTFS-Realtime**: Protocol Buffers parsing.
- **Pandas**: Data manipulation and merging.

## How it Works

1.  **Startup**: The API downloads the Static GTFS zip file (stops, routes, trips, stop_times) from UTA and caches it in memory. This happens once when the server starts.
2.  **Request**: When you request departures for a stop:
    - It fetches the **Live Trip Update** feed from UTA (protobuf format).
    - It parses the live feed to find updates for the specific stop ID.
    - It matches the live "Trip ID" with the cached Static data to find the Route Name (e.g., "Red Line") and Headsign.
3.  **Fallback**: If no live data is found (e.g., end of service, or tracking offline), the API queries the **Static Schedule** for the next 3 scheduled departures for the current day, using `calendar.txt` to validate service availability.
