import requests
import pandas as pd
import io
import zipfile
from google.transit import gtfs_realtime_pb2
from datetime import datetime
import time
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class GTFSService:
    STATIC_URL = "https://gtfsfeed.rideuta.com/GTFS.zip"
    REALTIME_URL = "https://apps.rideuta.com/tms/gtfs/TripUpdate"
    
    def __init__(self):
        self._static_cache = {}
        self._last_static_update = 0
        # Static data is loaded once at startup and cached in memory.
        self.trip_lookup = {}
        
    def load_static_data(self, force_refresh=False):
        """Loads static GTFS data if not already loaded."""
        if self._static_cache and not force_refresh:
            return

        logger.info("Downloading Static GTFS...")
        try:
            r = requests.get(self.STATIC_URL)
            r.raise_for_status()
            z = zipfile.ZipFile(io.BytesIO(r.content))
            
            def read_file(name):
                return pd.read_csv(z.open(name), dtype=str)

            logger.info("Parsing static files...")
            trips = read_file('trips.txt')
            routes = read_file('routes.txt')
            stops = read_file('stops.txt')
            stop_times = read_file('stop_times.txt')
            
            # Normalize Trip IDs: UTA Static IDs often have suffixes (e.g., 1234_WKD)
            # while Realtime IDs do not (e.g., 1234). We strip the suffix to ensure matching.
            trips['clean_trip_id'] = trips['trip_id'].apply(lambda x: x.split('_')[0])
            
            # Merge logic
            trips_merged = trips.merge(routes, on='route_id', how='left')
            
            # Store in cache
            self._static_cache['trips'] = trips_merged
            self._static_cache['stops'] = stops
            self._static_cache['stop_times'] = stop_times
            
            # Build a lookup table to map (Trip ID, Stop Sequence) -> Stop ID.
            # This is critical because the realtime feed provides Trip ID and Stop Sequence,
            # but not the Stop ID itself. We pre-compute this for O(1) access.
            logger.info("Building trip lookup table...")
            
            # Filter to necessary columns and cast sequence to int for matching
            st_lite = stop_times[['trip_id', 'stop_sequence', 'stop_id']].copy()
            st_lite['stop_sequence'] = st_lite['stop_sequence'].astype(int)
            
            self.trip_lookup = {}
            for tuple_row in st_lite.itertuples(index=False):
                # tuple_row is (trip_id, stop_sequence, stop_id)
                t_id = tuple_row.trip_id
                if t_id not in self.trip_lookup:
                    self.trip_lookup[t_id] = {}
                self.trip_lookup[t_id][tuple_row.stop_sequence] = tuple_row.stop_id
            
            logger.info("Static data loaded successfully.")
            self._last_static_update = time.time()
            
        except Exception as e:
            logger.error(f"Failed to load static data: {e}")
            raise

    def get_realtime_updates(self):
        """Fetches and parses the realtime feed."""
        if not self._static_cache:
            self.load_static_data()

        logger.info("Fetching live updates...")
        try:
            feed = gtfs_realtime_pb2.FeedMessage()
            response = requests.get(self.REALTIME_URL)
            response.raise_for_status()
            feed.ParseFromString(response.content)
            
            updates = []
            current_time = datetime.now().timestamp()
            
            for entity in feed.entity:
                if entity.HasField('trip_update'):
                    tu = entity.trip_update
                    trip_id = tu.trip.trip_id
                    
                    # Iterate through stop updates for this trip
                    for stu in tu.stop_time_update:
                        stop_id = None
                        
                        # Resolve the proper Stop ID using our pre-computed lookup table.
                        if trip_id in self.trip_lookup and stu.stop_sequence in self.trip_lookup[trip_id]:
                            stop_id = self.trip_lookup[trip_id][stu.stop_sequence]
                        
                        if stop_id:
                            arrival_ts = stu.arrival.time
                            # Exclude stale updates (older than 5 minutes).
                            if arrival_ts > current_time - 300:
                                updates.append({
                                    'clean_trip_id': trip_id,
                                    'stop_id': stop_id,
                                    'arrival_ts': arrival_ts,
                                    'delay': stu.arrival.delay if stu.arrival.HasField('delay') else 0
                                })
            
            return pd.DataFrame(updates)
            
        except Exception as e:
            logger.error(f"Failed to fetch realtime data: {e}")
            return pd.DataFrame()

    def search_stops(self, query: str):
        """Search for stops by name."""
        if not self._static_cache:
            self.load_static_data()
            
        stops = self._static_cache['stops']
        
        # Filter by name
        mask = stops['stop_name'].str.contains(query, case=False, na=False)
        results = stops[mask].head(20) # Limit to 20 results
        
        return results[['stop_id', 'stop_name', 'stop_lat', 'stop_lon']].to_dict('records')

    def get_departures_for_stop(self, stop_id_query):
        """Returns departure board for a specific stop."""
        df_rt = self.get_realtime_updates()
        
        if df_rt.empty:
            return {"error": "No active realtime trips found."}

        # Filter updates for the requested stop ID
        df_stop = df_rt[df_rt['stop_id'] == str(stop_id_query)].copy()

        # Get the name of the stop
        stop_name = self._static_cache['stops'][self._static_cache['stops']['stop_id'] == stop_id_query]['stop_name'].values[0]
        
        if df_stop.empty:
            return {"message": f"No upcoming realtime arrivals found for stop {stop_id_query}."}

        # Merge Realtime data with Static GTFS data to retrieve Route Name and Headsign.
        static_trips = self._static_cache['trips']
        merged = df_stop.merge(static_trips, on='clean_trip_id', how='left')
        
        # Prepare JSON response
        results = []
        for _, row in merged.head(10).iterrows():
            results.append({
                "route": row['route_short_name'] if pd.notna(row['route_short_name']) else "Unknown",
                "headsign": row['trip_headsign'] if pd.notna(row['trip_headsign']) else "Unknown",
                "arrival_time": datetime.fromtimestamp(row['arrival_ts']).isoformat()
            })
            
        return {"stop_id": stop_id_query, "stop_name": stop_name, "departures": results}

# Global instance for simplicity in this context
gtfs_service = GTFSService()
