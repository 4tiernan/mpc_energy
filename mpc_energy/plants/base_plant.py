from abc import ABC, abstractmethod
import datetime
from zoneinfo import ZoneInfo
import time
import numpy as np
import pandas as pd
import math
from collections import defaultdict
from typing import Any
import config_manager
from mpc_logger import logger
from exceptions import HAAPIError, SigenergyConnectionError, PlantControlError
from ha_api import HomeAssistantAPI
from loads.optional_loads import OptionalLoad
import data_helpers

class BasePlant(ABC):
    def __init__(self, ha: HomeAssistantAPI, optional_loads: list[OptionalLoad], plant_config: dict = None):
        self.ha: HomeAssistantAPI = ha
        self.optional_loads: list[OptionalLoad] = optional_loads
        self.plant_config = plant_config or {}
        self.local_tz: ZoneInfo = ha.local_tz
        
        self.time_step_minutes = 5
        self.load_avg_days = 3

        self.last_load_data_retrival_timestamp = 0
        self.avg_load_day = None

        self.history_since_midnight = None
    
    @abstractmethod
    def check_for_enabled_entites(self) -> None:
        """Checks to make sure all the entities needed for control are available and enabled, if not it raises an error."""
        pass

    @abstractmethod
    def update_data(self):
        """Update all plant-specific data from Home Assistant."""
        pass

    @abstractmethod
    def historical_data(self):
        """Update all plant-specific data from Home Assistant."""
        pass

    @abstractmethod
    def system_curtailing(self) -> dict:
        """Returns a dict indicating if the system is currently being curtailed and the reason for curtailment if applicable."""
        return {
            "curtailed": False,
            "reason": None
        }
        
    def get_config_entry_value(self, entry_id) -> Any:
        """Try to get the value from a config entry that is either a string float or an entity id."""
        try:
            val = float(entry_id)
            if(val != None and val > 0):
                return val
            else:
                logger.error(f"Value set for {entry_id} : {val} is invailid.")
        except (ValueError, TypeError):
            try:
                # If the config entry id cannot be parsed as a float it should be the entity_id
                val = self.get_sigenergy_numeric_state(entry_id)
                return val  
            except Exception as e:
                logger.error(f"Unable to get entity id or float from config entry '{entry_id}'. Please check the entity id or ensure it is a float. Exception: {e}")

    def get_optional_config_entry_value(self, entry_id, default_value=0.0) -> float:
        """Get an optional config entry value, returning a default if not found or invalid."""
        if(entry_id is None or entry_id == ""):
            return float(default_value)
        try:
            val = self.get_config_entry_value(entry_id)
            if(val is None):
                return float(default_value)
            return float(val)
        except Exception:
            logger.warning(f"Unable to read optional config value '{entry_id}', defaulting to {default_value}.")
            return float(default_value)
        
    def get_profit_history(self) -> list[data_helpers.BinnedStateClass]:
        """Get the history required for the profit calcs and use cached data if its not too old to avoid the expensive historical data retrieval and processing if possible."""
        now = datetime.datetime.now(self.local_tz)
        rounded_now = data_helpers.round_minutes(time=now, nearest_minute=self.time_step_minutes)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        if self.history_since_midnight is not None and self.history_since_midnight.get("time_index"):
            first_cached_timestamp = self.history_since_midnight["time_index"][0]
            first_cached_dt = datetime.datetime.fromisoformat(first_cached_timestamp)
            # Reset the cache at local midnight so "today" calculations do not include yesterday's bins.
            if first_cached_dt.date() != now.date():
                self.history_since_midnight = None

        if self.history_since_midnight == None:
            self.history_since_midnight = self.historical_data(start_datetime=today_start, end_datetime=rounded_now, bin_period=self.time_step_minutes)
            return self.history_since_midnight
        else:
            last_history_timestamp = self.history_since_midnight['time_index'][-1]
            start = datetime.datetime.fromisoformat(last_history_timestamp)
            end = now
            minutes_since_last_history = (end - start).total_seconds() / 60
            if minutes_since_last_history > self.time_step_minutes: # If the history is more than 5 minutes old, get new history
                latest_history = self.historical_data(start_datetime=start, end_datetime=rounded_now, bin_period=self.time_step_minutes)
                logger.debug(f"Updating profit history cache with {len(latest_history['time_index'])} new data points spanning from {latest_history['time_index'][0]} to {latest_history['time_index'][-1]}.")

                last_ts = self.history_since_midnight["time_index"][-1]
                new_times = latest_history["time_index"]

                if new_times and new_times[0] == last_ts:
                    # Override the last cached point with latest recomputed point
                    for k in self.history_since_midnight.keys():
                        self.history_since_midnight[k][-1] = latest_history[k][0]
                    start_idx = 1
                else:
                    # No exact overlap found at first point; append from first strictly newer point
                    start_idx = 0
                    while start_idx < len(new_times) and new_times[start_idx] <= last_ts:
                        start_idx += 1

                # Append remaining new points
                for k in self.history_since_midnight.keys():
                    self.history_since_midnight[k].extend(latest_history[k][start_idx:])

        return self.history_since_midnight

    def calculate_today_profit_cost(self) -> None:
        """Get today's historical data and calculate profit and cost."""
        history = self.get_profit_history()

        now = datetime.datetime.now(self.local_tz)

        # Check to see if the requested amount of data was recieved, use the configured default if not
        if(len(history['prices_sell']) < 2):
            if(now.time() > datetime.time(0,30)): # If its early in the day, its likely there just isn't enough history yet, so don't log a warning and set profit to 0
                logger.error(f"Insufficent data to calulate profit.")
            self.daily_export_profit = 0
            self.daily_import_cost = 0
            self.daily_net_profit = 0
            return

        # Convert lists to numpy arrays
        export_cumsum = np.array(history["grid_export_kwh"])
        import_cumsum = np.array(history["grid_import_kwh"])
        prices_sell = np.array(history["prices_sell"])
        prices_buy = np.array(history["prices_buy"])

        # Compute per-bin kWh by taking the difference between consecutive cumulative readings
        export_kwh_bin = np.diff(export_cumsum, prepend=export_cumsum[0])  # prepend first element so first bin is correct
        import_kwh_bin = np.diff(import_cumsum, prepend=import_cumsum[0])

        export_kwh_bin = np.where(export_kwh_bin < 0, 0, export_kwh_bin) # Remove negative values (import and export should only increment positivley)
        import_kwh_bin = np.where(import_kwh_bin < 0, 0, import_kwh_bin)

        # Element-wise multiply by corresponding prices
        profit_per_bin = export_kwh_bin * prices_sell
        cost_per_bin = import_kwh_bin * prices_buy

        # Sum up total profit, total cost, net profit
        self.daily_export_profit = np.sum(profit_per_bin)
        self.daily_import_cost = np.sum(cost_per_bin)
        self.daily_net_profit = self.daily_export_profit - self.daily_import_cost
    
    def validate_returned_data_timedelta(self, data: list[data_helpers.BinnedStateClass], requested_start: datetime.datetime, requested_end: datetime.datetime, tollerance_minutes: float = 30) -> bool:
        '''
        data -> array containing datetime objs (data[i].time) for each datapoint
        returns True if the requested amount of data was returned.
        '''
        if(not data):
            logger.error(f"No data returned from the api for the requested times: Start: {requested_start}, End: {requested_end}")
            return False
        else:
            first_time = data[0].time
            last_time = data[-1].time

            # Determine if less data time span was returned than requested
            expected_span = requested_end - requested_start
            actual_span = last_time - first_time 

            # If 30 mintues less data than expected was returned, use the estimated load energy configured.
            if actual_span < expected_span - datetime.timedelta(minutes=tollerance_minutes):
                expected_hours = expected_span.total_seconds() / 3600.0
                actual_hours = max(actual_span.total_seconds(), 0.0) / 3600.0
                logger.warning(
                    f"Requested {round(expected_hours, 1)} hours of history but received "
                    f"{round(actual_hours, 1)} hours."
                )
                return False
        return True

    def update_load_avg(self, days_ago=7) -> list[data_helpers.BinnedStateClass]:
        '''Calculate the average load power profile for a day based on the past load history.'''

        # Determine the start and end datetimes for the requested history based on the number of days ago to look back from
        today = datetime.datetime.now(self.local_tz).date()
        end_date = today - datetime.timedelta(days=1) # Today doesn't have a full day so only go up to yesterday
        start_date = end_date - datetime.timedelta(days=days_ago)

        start = datetime.datetime.combine(start_date, datetime.time.min, tzinfo=self.local_tz)
        end = datetime.datetime.combine(end_date, datetime.time.max, tzinfo=self.local_tz)

        load_power_history = self.ha.get_history(config_manager.load_power_entity_id, start_time=start, end_time=end)

        # Check to see if the requested amount of data was recieved, use the configured default if not
        if(not self.validate_returned_data_timedelta(data=load_power_history, requested_start=start, requested_end=end)):
            configured_avg_load = self.plant_config.get("estimated_daily_load_energy_consumption", 24.0)
            logger.warning(f"Using default load energy of {configured_avg_load} kWh per day.")

            # Create a linearly spaced array climbing from 0 to the total load over a day
            avg_day = []
            for i in range(int(24 * 60 / self.time_step_minutes)):
                t = (datetime.datetime.min + datetime.timedelta(minutes=i * self.time_step_minutes)).time()
                val = (i / (24 * 60 / self.time_step_minutes)) * configured_avg_load
                avg_day.append(data_helpers.BinnedStateClass(avg_state=round(val, 2), states=[], time=t))

            return avg_day # Return the avg day with the default load profile
        

        # Bin whole history first
        binned_load_history = data_helpers.bin_data(load_power_history, self.time_step_minutes, start, end)
        
        # Debias using optional loads if provided
        if self.optional_loads:
            for load in self.optional_loads:
                opt_history = load.get_historical_power(start=start, end=end, bin_period=self.time_step_minutes)
                if opt_history:
                    logger.debug(f"Debiasing load history using optional load: {load.name}")
                    for i in range(min(len(binned_load_history), len(opt_history))):
                        opt_val = opt_history[i].avg_state or 0.0
                        binned_load_history[i].avg_state = max(binned_load_history[i].avg_state - opt_val, 0.0)

        # Split binned history into days
        history_by_day = defaultdict(list)
        for b in binned_load_history:
            try:
                history_by_day[b.time.date()].append(b)
            except AttributeError:
                pass # Handle cases where bin might not have a date
        
        # --- Bin history data by day--- 
        per_day_binned = []
        expected_bins_per_day = int(24 * 60 / self.time_step_minutes)
        for day, day_data in history_by_day.items():
            try:
                # Only include days that have at least the expected number of bins
                # This avoids partial days (like a single midnight bin) causing index errors.
                if len(day_data) >= expected_bins_per_day:
                    per_day_binned.append(day_data[:expected_bins_per_day])
                else:
                    logger.debug(f"Day {day} has {len(day_data)} bins, expected {expected_bins_per_day}. Data: {day_data}")
                    logger.warning(f"Skipping day {day} for average load calculation due to insufficient data bins: expected {expected_bins_per_day}, got {len(day_data)}.")
            except Exception as e:
                logger.warning(f"Skipping day {day} due to binning error: {e}")

        if not per_day_binned:
            raise PlantControlError("No valid daily data after binning.")
        

        # --- Build average day ---
        num_bins = len(per_day_binned[0])
        avg_day = []

        for i in range(num_bins):
            states = []

            for day_bins in per_day_binned:
                val = day_bins[i].avg_state
                if val is not None and not math.isnan(val):
                    states.append(val)

            if states:
                avg_val = round(sum(states) / len(states), 2)
                avg_val = max(avg_val, 0.0) # Ensure no negative values

            else:
                raise PlantControlError(f"No valid data for time bin {per_day_binned[0][i].time.time()} across all days.")

            avg_day.append(
                data_helpers.BinnedStateClass(
                    avg_state=avg_val,
                    states=states,
                    time=per_day_binned[0][i].time.time()
                )
            )
        
        return avg_day

    def round_forecast_times(self, forecast_hours_from_now=None, forecast_till_time=None, forecast_start_time=None, forecast_end_time=None):
        if forecast_start_time is not None and forecast_end_time is not None:
            rounded_current_time = data_helpers.round_minutes(forecast_start_time, nearest_minute=self.time_step_minutes)
            rounded_forecast_time = data_helpers.round_minutes(forecast_end_time, nearest_minute=self.time_step_minutes)
            return [rounded_current_time, rounded_forecast_time]
        
        rounded_current_time = data_helpers.round_minutes(datetime.datetime.now(self.local_tz), nearest_minute=self.time_step_minutes)
        if(forecast_hours_from_now):
            rounded_forecast_time = data_helpers.round_minutes(rounded_current_time + datetime.timedelta(hours=forecast_hours_from_now), nearest_minute=self.time_step_minutes)
        elif(forecast_till_time):
            rounded_forecast_time = datetime.datetime.combine(rounded_current_time.date(), forecast_till_time, tzinfo=self.local_tz)
            rounded_forecast_time = data_helpers.round_minutes(rounded_forecast_time, nearest_minute=self.time_step_minutes)
            if(rounded_forecast_time <= rounded_current_time):
                rounded_forecast_time = rounded_forecast_time + datetime.timedelta(days=1)
        else:
            raise Exception("Must provide forecast hours or time to determine forecast!")
        
        return [rounded_current_time, rounded_forecast_time]
    
    def get_load_avg(self, days_ago, hours_update_interval=24) -> list[data_helpers.BinnedStateClass]:
        """Return the average load profile for a day based on the load history. Uses cached value if the last retrieval was within the update interval."""

        if(time.time() - self.last_load_data_retrival_timestamp > hours_update_interval*60*60 or self.avg_load_day == None):
            self.avg_load_day = self.update_load_avg(days_ago)
            self.last_load_data_retrival_timestamp = time.time()
        return self.avg_load_day
    
    def forecast_load_power(self, forecast_hours_from_now=None, forecast_till_time=None, forecast_start_time=None, forecast_end_time=None) -> list[data_helpers.BinnedStateClass]:
        avg_day = self.get_load_avg(days_ago=self.load_avg_days)

        # Determine the current and the end of the forecast datetimes, both rounded to 5 min
        [rounded_current_time, rounded_forecast_time] = self.round_forecast_times(
            forecast_hours_from_now,
            forecast_till_time,
            forecast_start_time=forecast_start_time,
            forecast_end_time=forecast_end_time,
        )

        # Create a lookup dict for each time bin: time-of-day → kWh per bin
        avg_day_kw_lookup = {bin.time: bin.avg_state for bin in avg_day}

        forecast_power = []
        forecast_steps = int((rounded_forecast_time - rounded_current_time).total_seconds() // (self.time_step_minutes * 60))

        avg_kw_per_bin = sum(b.avg_state for b in avg_day) / len(avg_day) # Used below to fallback if no data for specific bin

        for i in range(forecast_steps):
            point_time = rounded_current_time + datetime.timedelta(minutes=self.time_step_minutes * i)

            # Get kW for this time-of-day bin
            power = avg_day_kw_lookup.get(point_time.time())

            # Fallback if missing
            if power is None or math.isnan(power) or power <= 0:
                power = avg_kw_per_bin

            forecast_power.append(
                data_helpers.BinnedStateClass(
                    avg_state=power,
                    states=[],
                    time=point_time
                )
            )

        return forecast_power
            
    def forecast_consumption_amount(self, forecast_hours_from_now=None, forecast_till_time=None, ) -> float:
        avg_day = self.get_load_avg(days_ago=self.load_avg_days)

        [rounded_current_time, rounded_forecast_time] = self.round_forecast_times(forecast_hours_from_now, forecast_till_time)

        # Lookup: time-of-day → kW per bin
        avg_day_kw_lookup = {bin.time: bin.avg_state for bin in avg_day}

        step_minutes = self.time_step_minutes
        forecast_steps = int(
            (rounded_forecast_time - rounded_current_time).total_seconds()
            // (step_minutes * 60)
        )
            
        total_kwh = 0.0

        avg_kw_per_bin = sum(b.avg_state for b in avg_day) / len(avg_day) # Used below to fallback if no data for specific bin

        for i in range(forecast_steps):
            point_time = rounded_current_time + datetime.timedelta(minutes=step_minutes * i)

            kw = avg_day_kw_lookup.get(point_time.time())

            # Fallback if missing
            if kw is None or math.isnan(kw):
                kw = avg_kw_per_bin

            total_kwh += kw * (step_minutes / 60)  # Convert kW to kWh for the time step

        return total_kwh
    
    def kwh_required_remaining(self) -> float:
        """Returns the forecasted kWh required from now until sunrise tomorrow (6am) based on the average load profile."""
        forecast_kwh = self.forecast_consumption_amount(forecast_till_time=datetime.time(6, 0, 0))
        return forecast_kwh
    
    def kwh_required_till_sundown(self) -> float:
        """Returns the forecasted kWh required from now until sundown based on the average load profile."""
        forecast_kwh = self.forecast_consumption_amount(forecast_till_time=datetime.time(18, 0, 0))
        return forecast_kwh
            
    def forecast_solar_power(self, forecast_hours_from_now, forecast_start_time=None, forecast_end_time=None) -> list[float]:
        """Returns the forecast solar power for the requested time period in 5 minute increments. If start and end times are provided, they will be used to determine the forecast horizon, otherwise the forecast_hours_from_now will be used."""
        if forecast_start_time is not None and forecast_end_time is not None:
            rounded_start_time = data_helpers.round_minutes(forecast_start_time, nearest_minute=self.time_step_minutes)
            rounded_end_time = data_helpers.round_minutes(forecast_end_time, nearest_minute=self.time_step_minutes)
            forecast_seconds = max((rounded_end_time - rounded_start_time).total_seconds(), 0)
            forecast_hours = forecast_seconds / 3600
            N_5min = max(0, int(forecast_seconds // (self.time_step_minutes * 60)))
        else:
            forecast_hours = float(forecast_hours_from_now)
            N_5min = max(0, int(np.ceil(forecast_hours * (60 / self.time_step_minutes))))

        N_30min = max(0, int(np.ceil(N_5min / (30 // self.time_step_minutes))))
        interpolation_steps = 30 // self.time_step_minutes

        # Solar Forecast
        # Get solar forecast list from HA
        today = self.ha.get_state(config_manager.solcast_forecast_today_entity_id)["attributes"]["detailedForecast"]
        tomorrow = self.ha.get_state(config_manager.solcast_forecast_tomorrow_entity_id)["attributes"]["detailedForecast"]

        forecast = today + tomorrow # Combine

        if(forecast_hours > 24):
            day_3_forecast = self.ha.get_state(config_manager.solcast_forecast_day_3_entity_id)["attributes"]["detailedForecast"]
            forecast = forecast + day_3_forecast # Add day 3's forecast to the list if requesting more than 24 hrs of forecast
        
        if(forecast_hours > 48):
            day_4_forecast = self.ha.get_state(config_manager.solcast_forecast_day_4_entity_id)["attributes"]["detailedForecast"]
            forecast = forecast + day_4_forecast # Add day 4's forecast to the list if requesting more than 48 hrs of forecast
        
        df = pd.DataFrame(forecast) # Convert to DataFrame for easy time handling
        
        df["period_start"] = pd.to_datetime(df["period_start"]) # Parse timestamps (Solcast provides timezone-aware ISO strings)

        # Current time in same timezone
        if forecast_start_time is not None:
            now = pd.Timestamp(data_helpers.round_minutes(forecast_start_time, nearest_minute=self.time_step_minutes))
            if df["period_start"].dt.tz is not None and now.tzinfo is None:
                now = now.tz_localize(df["period_start"].dt.tz)
            elif df["period_start"].dt.tz is not None and now.tzinfo is not None:
                now = now.tz_convert(df["period_start"].dt.tz)
        else:
            now = pd.Timestamp.now(tz=df["period_start"].dt.tz)
            now = now.ceil(f"{self.time_step_minutes}min") #round to nearest time step

        # Keep only future (or current) periods
        df_future = (
            df[df["period_start"] >= now]
            .sort_values("period_start")
            .iloc[:N_30min]
        )

        # Solar forecast (kW)
        solar_30min = df_future["pv_estimate"].to_numpy()
        solar_30min = solar_30min[:N_30min]

        if len(solar_30min) == 0:
            logger.warning("Solcast returned no future 30 minute forecast intervals. Falling back to zero solar forecast.")
            return np.zeros(N_5min)

        if len(solar_30min) < N_30min:
            logger.warning(f"Solcast forecast shorter than requested horizon. Requested 30 min bins={N_30min}, received={len(solar_30min)}. Extending with last known value.")

        solar_30min_x = np.arange(0, len(solar_30min) * interpolation_steps, interpolation_steps)
        solar_5min = np.interp(np.arange(N_5min), solar_30min_x, solar_30min)
        
        return solar_5min[:N_5min] # return the solar forecast but limit the list length to the requested length
