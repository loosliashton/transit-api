import requests
import pandas as pd
import io
import zipfile
from google.transit import gtfs_realtime_pb2
from datetime import datetime
import time
import logging
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class GTFSService:
    STATIC_URL = os.getenv('GTFS_STATIC_URL')
    REALTIME_URL = os.getenv('GTFS_REALTIME_URL')
    
    TYPE_REALTIME = "realtime"
    TYPE_SCHEDULED = "scheduled"
    
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
            calendar = read_file('calendar.txt')
            calendar_dates = read_file('calendar_dates.txt')
            
            # Normalize Trip IDs: UTA Static IDs often have suffixes (e.g., 1234_WKD)
            # while Realtime IDs do not (e.g., 1234). We strip the suffix to ensure matching.
            trips['clean_trip_id'] = trips['trip_id'].apply(lambda x: x.split('_')[0])
            
            # Merge logic
            trips_merged = trips.merge(routes, on='route_id', how='left')
            
            # Store in cache
            self._static_cache['trips'] = trips_merged
            self._static_cache['stops'] = stops
            self._static_cache['stop_times'] = stop_times
            self._static_cache['calendar'] = calendar
            self._static_cache['calendar_dates'] = calendar_dates
            
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



    def get_active_service_ids(self):
        """Returns a set of service_ids active for the current day."""
        if not self._static_cache:
            self.load_static_data()

        now = datetime.now()
        current_date_str = now.strftime('%Y%m%d')
        day_of_week = now.strftime('%A').lower()  # e.g., 'monday'

        active_services = set()
        
        # 1. Check calendar.txt
        cal = self._static_cache.get('calendar')
        if cal is not None:
            # Filter by date range
            mask = (cal['start_date'] <= current_date_str) & (cal['end_date'] >= current_date_str)
            # Filter by day of week
            mask = mask & (cal[day_of_week] == '1')
            active_services.update(cal[mask]['service_id'].unique())

        # 2. Check calendar_dates.txt (exceptions)
        cal_dates = self._static_cache.get('calendar_dates')
        if cal_dates is not None:
            # Exception type 1 = Added service, 2 = Removed service
            day_exceptions = cal_dates[cal_dates['date'] == current_date_str]
            
            added = day_exceptions[day_exceptions['exception_type'] == '1']['service_id']
            removed = day_exceptions[day_exceptions['exception_type'] == '2']['service_id']
            
            active_services.update(added)
            active_services.difference_update(removed)
            
        return active_services

    def _parse_gtfs_time(self, time_str: str, now: datetime) -> str:
        """Parses GTFS time string (HH:MM:SS) handling >24h times."""
        h, m, s = map(int, time_str.split(':'))
        target_date = now
        
        if h >= 24:
            h -= 24
            target_date = now + pd.Timedelta(days=1)
            
        try:
            return target_date.replace(hour=h, minute=m, second=s, microsecond=0).isoformat()
        except ValueError:
            return time_str

    def get_scheduled_departures(self, stop_id_query: str) -> pd.DataFrame:
        """
        Get scheduled departures for today when realtime is unavailable.
        
        Args:
            stop_id_query: The ID of the stop to query.
            
        Returns:
            pd.DataFrame: DataFrame containing trip details and formatted arrival times.
                          Returns empty DataFrame if stop not found or no trips.
        """
        service_ids = self.get_active_service_ids()
        stops = self._static_cache['stops']
        
        # Get stop name safely
        stop_rows = stops[stops['stop_id'] == str(stop_id_query)]
        if stop_rows.empty:
            return pd.DataFrame() 
        
        # 1. Filter Trips by Service ID
        trips = self._static_cache['trips']
        active_trips = trips[trips['service_id'].isin(service_ids)]
        
        # 2. Filter Stop Times by Stop ID and Active Trips
        stop_times = self._static_cache['stop_times']
        st_filtered = stop_times[stop_times['stop_id'] == str(stop_id_query)]
        st_filtered = st_filtered[st_filtered['trip_id'].isin(active_trips['trip_id'])]
        
        # 3. Filter by Time (Future only)
        now = datetime.now()
        now_str = now.strftime('%H:%M:%S')
        # Simple string comparison works for HH:MM:SS format
        future_st = st_filtered[st_filtered['departure_time'] > now_str].sort_values('departure_time')
        
        # 4. Join with Trips to get Headsign/Route
        merged = future_st.head(3).merge(active_trips, on='trip_id', how='left')
        
        if merged.empty:
            return pd.DataFrame()

        # Calculate formatted times using apply
        merged['formatted_arrival_time'] = merged['departure_time'].apply(
            lambda t: self._parse_gtfs_time(t, now)
        )
        
        return merged

    def search_stops(self, query: str) -> list[dict]:
        """
        Search for stops by name.
        
        Args:
            query: The name to search for (case-insensitive).
            
        Returns:
            list[dict]: List of matching stop dictionaries with keys: stop_id, stop_name, stop_lat, stop_lon.
        """
        if not self._static_cache:
            self.load_static_data()
            
        stops = self._static_cache['stops']
        
        # Filter by name
        mask = stops['stop_name'].str.contains(query, case=False, na=False)
        results = stops[mask].head(20) # Limit to 20 results
        
        return results[['stop_id', 'stop_name', 'stop_lat', 'stop_lon']].to_dict('records')

    def get_departures_for_stop(self, stop_id_query: str) -> dict:
        """
        Returns departure board for a specific stop.
        
        Args:
            stop_id_query: The ID of the stop.
            
        Returns:
            dict: JSON-compatible response with stop info and departure list.
                  Returns {"error": ...} on failure.
        """
        # Ensure static data is loaded
        if not self._static_cache:
            self.load_static_data()

        # Validate stop and get name
        stops = self._static_cache['stops']
        stop_rows = stops[stops['stop_id'] == str(stop_id_query)]
        
        if stop_rows.empty:
             return {"error": f"Stop {stop_id_query} not found."}
        
        stop_name = stop_rows['stop_name'].values[0]
        final_df = pd.DataFrame()
        dep_type = self.TYPE_SCHEDULED

        # Try Realtime
        try:
            df_rt = self.get_realtime_updates()
            if not df_rt.empty:
                 # Filter updates for the requested stop ID
                 df_stop = df_rt[df_rt['stop_id'] == str(stop_id_query)].copy()
                 
                 if not df_stop.empty:
                    # Merge Realtime data with Static GTFS data
                    static_trips = self._static_cache['trips']
                    final_df = df_stop.merge(static_trips, on='clean_trip_id', how='left').head(10)
                    
                    if not final_df.empty:
                        # Calculate formatted arrival time for realtime
                        final_df['formatted_arrival_time'] = final_df['arrival_ts'].apply(
                            lambda ts: datetime.fromtimestamp(ts).isoformat()
                        )
                        dep_type = self.TYPE_REALTIME

        except Exception as e:
            logger.error(f"Realtime fetch failed: {e}")

        # If no realtime results, fallback to schedule
        if final_df.empty:
            logger.info(f"No live updates for stop {stop_id_query}, falling back to schedule.")
            final_df = self.get_scheduled_departures(stop_id_query)
            dep_type = self.TYPE_SCHEDULED

        # Build final response
        results = []
        if not final_df.empty:
            for _, row in final_df.iterrows():
                results.append({
                    "route": row['route_short_name'] if pd.notna(row['route_short_name']) else "Unknown",
                    "headsign": row['trip_headsign'] if pd.notna(row['trip_headsign']) else "Unknown",
                    "arrival_time": row['formatted_arrival_time'],
                    "departure_type": dep_type
                })
            
        return {"stop_id": stop_id_query, "stop_name": stop_name, "departures": results}

# Global instance for simplicity in this context
gtfs_service = GTFSService()
