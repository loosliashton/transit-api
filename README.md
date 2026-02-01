# UTA Realtime Transit API

A lightweight Python API using FastAPI to serve realtime departure boards for Utah Transit Authority (UTA) stops.

## Features

- **Realtime Data**: Fetches live Trip Updates from UTA's GTFS-Realtime feed.
- **Auto-Matching**: Automatically correlates live trip IDs with static schedules to provide Route Names and Headsigns.
- **Search**: Integrated stop search endpoint.

## Setup

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
