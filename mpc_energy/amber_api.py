import requests
import time
import numpy as np
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from mpc_logger import logger
from exceptions import (
    AmberAPIConnectionError,
    AmberAPIRequestError,
    AmberAPITimeoutError,
    AmberAPIError,
)


@dataclass
class PriceForecast:
    price: float
    start_time: datetime
    end_time: datetime
    demand_window: bool # True if the current price is in a demand window

@dataclass
class amber_data:
    demand_tarrif_price: float
    general_price: float
    feedIn_price: float
    prices_estimated: bool
    general_max_forecast_price: float
    feedIn_max_forecast_price: float
    general_12hr_forecast: list[PriceForecast]
    feedIn_12hr_forecast: list[PriceForecast]
    general_12hr_forecast_sorted: list[PriceForecast]
    feedIn_12hr_forecast_sorted: list[PriceForecast]
    general_extrapolated_forecast: list[float]
    feedIn_extrapolated_forecast: list[float]
    demand_window_extrapolated_forecast: list[bool]  # True for each 5-min interval that falls in a demand window
    

class AmberAPI:
    def __init__(self, api_key, site_id, local_tz=None, demand_price="", errors=True):
        self.api_key = api_key
        self.site_id = site_id
        self.local_tz = local_tz
        self.base = "https://api.amber.com.au/v1"

        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json"
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.errors = True
        self.rate_limit_remaining = None
        self.seconds_till_rate_limit_reset = None
        self.data = None

        if(self.site_id != ""): # Only check for a demand tarrif if the site has been entered.
            self.demand_tarrif = self.check_for_demand_tarrif() # True if user is on a demand tarrif. 
            self.demand_tarrif_price = None

            if(self.demand_tarrif):
                logger.info("The selected site is on a demand tarrif. Adjusting MPC accordingly.")
                if(demand_price == ""):
                    logger.error("The Amber API has specified that you are on a demand tarrif but no demand price has been entered into the config. Please enter a demand price ($/kW)")
                    exit()
                else:
                    try: 
                        self.demand_tarrif_price = float(demand_price)
                    except:
                        logger.error(f"The demand price enertered in the configuration: '{demand_price}' could not be converted to a float. Please only enter a numeric value.")    
                        exit()
                
            else:
                logger.info("No demand tarrif detected continuning normally.")

    def send_request(self, url):
        connect_timeout = 10
        response_timeout = 30

        try:
            r = self.session.get(url, headers=self.headers, timeout=(connect_timeout,response_timeout))
        except requests.exceptions.Timeout:
            raise AmberAPITimeoutError("Amber API timeout. Your internet connection may be down, or the Amber server may be unavailable.") from None

        except requests.exceptions.ConnectionError:
            raise AmberAPIConnectionError("Amber API connection error") from None
           

        except requests.exceptions.RequestException as e:
            raise AmberAPIRequestError(f"Amber API error: {e}") from None
            

        self.rate_limit_remaining = r.headers.get("RateLimit-Remaining")
        self.seconds_till_rate_limit_reset = r.headers.get("RateLimit-Reset")
        if(self.rate_limit_remaining != None):
            self.rate_limit_remaining = int(self.rate_limit_remaining)
        else:
            self.rate_limit_remaining = 0
        if(self.seconds_till_rate_limit_reset != None):
            self.seconds_till_rate_limit_reset = int(self.seconds_till_rate_limit_reset)
        else: 
            self.seconds_till_rate_limit_reset = 0

        #print(f"Seconds till reset: {self.seconds_till_rate_limit_reset}")
        #logger.info(f"Amber Site Retreval HTML status Code: {r.status_code}, response: {r.json()}")
        # Check for rate limiting
        if r.status_code == 429:
            if self.seconds_till_rate_limit_reset:
                logger.error(f"Exceeded Amber API request rate limit.")
                logger.error(f"Waiting {self.seconds_till_rate_limit_reset+5} seconds before retrying")
                time.sleep(int(self.seconds_till_rate_limit_reset+5))
            else:
                logger.error(r)
                logger.error(r.headers)
                logger.error(f"Exceeded AmazonAWS Amber API request rate limit. Note this is an issue with the Amber API not MPC Energy, please ignore.")
                logger.error(f"Waiting 10 seconds before retrying")
                time.sleep(10)
            return self.send_request(url)

        elif r.status_code == 403:
            logger.error("API key provided for Amber API does not have authorisation to access the Amber API. Please check the key is correct or create a new key.")
            exit()
        
        return r.json()

    def get_sites(self):
        """Return all sites linked to your Amber account."""
        url = f"{self.base}/sites"
        response = self.send_request(url)
        if(response):
            return response
        else:
            raise AmberAPIError("Failed to retrieve sites from API.")
            
    def check_for_demand_tarrif(self):
        """Returns True if the site selected has a demand tarrif, else False"""
        url = (f"{self.base}/sites/{self.site_id}/prices/current?next=0&previous={48}&resolution={30}")

        response = self.send_request(url)

        if(response, len(response) >= 2):
            for i in response:
                if 'tariffInformation' in i:
                    tarrif_info = i['tariffInformation']
                    if("demandWindow" in tarrif_info): # Check to see if the demand window key exists in the tarrif information, indicating the user is on a demand tarrif. 
                        return True
                
            return False
        else:
            raise AmberAPIError("Failed to check for demand tarrif.")

    def get_past_prices(self, previous_intervals, resolution):
        """Return historic prices for a given site."""
        if(resolution != 30 and resolution != 5):
            if(self.errors):
                raise("Resolution must be 5 or 30 minutes not: "+str(resolution))

        url = (f"{self.base}/sites/{self.site_id}/prices/current?next=0&previous={previous_intervals}&resolution={resolution}")

        previous_general_prices = []
        previous_feed_in_price = []
        date_format = "%Y-%m-%dT%H:%M:%SZ"

        response = self.send_request(url)
            
        if(response and len(response) >= 2):
            for i in response:
                start = datetime.strptime(i["startTime"], date_format).replace(tzinfo=timezone.utc).astimezone(self.local_tz)
                end   = datetime.strptime(i["endTime"], date_format).replace(tzinfo=timezone.utc).astimezone(self.local_tz)

                if i["channelType"] == "general":
                    price = i["perKwh"] 
                    demand_window = self.demand_window_present(i)

                    interval = PriceForecast(price=price, start_time=start, end_time=end, demand_window=demand_window)
                    previous_general_prices.append(interval)

                elif i["channelType"] == "feedIn":
                    price = -i["perKwh"] 
                    interval = PriceForecast(price=price, start_time=start, end_time=end, demand_window=False)  
                    previous_feed_in_price.append(interval)

            return [previous_general_prices, previous_feed_in_price]
        
        else:
            raise AmberAPIError("Failed to get past price data.")
    
    def demand_window_present(self, interval):
        demand_window = False
        if(self.demand_tarrif):
            try:
                demand_window = bool(interval['tariffInformation']['demandWindow'])
            except:
                    logger.warning(f"No demand window flag was found in api call but site is marked as having a demand tarrif. Interval Data '{interval}'")
        
        return demand_window
                
    def get_forecast(self, next_intervals, resolution, advanced_forecast = False):
        """Return 12 hours of prices from now for a given site."""
        if(resolution != 30 and resolution != 5):
            if(self.errors):
                raise("Resolution must be 5 or 30 minutes not: "+str(resolution))

        url = (f"{self.base}/sites/{self.site_id}/prices/current?next={next_intervals}&previous=0&resolution={resolution}")

        general_price_forecast = []
        feed_in_price_forecast = []
        date_format = "%Y-%m-%dT%H:%M:%SZ"

        response = self.send_request(url)

        if(response and len(response) >= 2):
            for i in response:
                start = datetime.strptime(i["startTime"], date_format).replace(tzinfo=timezone.utc).astimezone(self.local_tz)
                end   = datetime.strptime(i["endTime"], date_format).replace(tzinfo=timezone.utc).astimezone(self.local_tz)

                if i["channelType"] == "general":
                    if("advancedPrice" in i and advanced_forecast == True):
                        price = i["advancedPrice"]["predicted"]
                    else:
                        price = i["perKwh"]
                    demand_window = self.demand_window_present(i)

                    interval = PriceForecast(price=price, start_time=start, end_time=end, demand_window=demand_window)   
                    general_price_forecast.append(interval)

                elif i["channelType"] == "feedIn":
                    if("advancedPrice" in i and advanced_forecast == True):
                        price = -i["advancedPrice"]["predicted"]
                    else:
                        price = -i["perKwh"]   
                    interval = PriceForecast(price=price, start_time=start, end_time=end, demand_window=False) 
                    feed_in_price_forecast.append(interval)

            return [general_price_forecast, feed_in_price_forecast]

        else:
            raise AmberAPIError("Failed to get price forecast data")
    
    # Get the 5 min, 30 min and past prices and combine into a 5 minutely 'forecast' that extends past the 12 hr limit
    def get_extrapolated_forecast_old(self, hours, advanced_forecast = False): 
        N_30min = int(hours / (30/60)) # Number of 30 min segments requested
        N_5min = int(hours / (5/60))   # Number of 5 min segments requested

        amber_forecast_30min_intervals = (60//30)*12    # Get the max 12hr forecast
        amber_past_30min_intervals = max(N_30min - amber_forecast_30min_intervals, 0)  # Fill the rest of the sim with past prices
    
        # Get the 5 minutely price forecasts
        [general_price_forecast_5_min_data, feed_in_price_forecast_5_min_data] = self.get_forecast(next_intervals=60//5, resolution=5, advanced_forecast=advanced_forecast)

        # Get the 30 minutely forecast
        [general_price_forecast_30_min_data, feed_in_price_forecast_30_min_data] = self.get_forecast(next_intervals=amber_forecast_30min_intervals, resolution=30, advanced_forecast=advanced_forecast)

        # Getz the past prices to form the 2nd half of the 24hr forecast due to the 12hr limit on forecasts
        [past_general_30_min_data, past_feed_in_30_min_data] = self.get_past_prices(amber_past_30min_intervals, resolution=30)

        # Build a 5-minute forecast keyed by the timestamps returned by Amber.
        # Start with 30-minute intervals expanded to 5-minute points, then overwrite
        # those points with the native 5-minute data where available.
        general_points = {}
        feed_in_points = {}
        demand_window_points = {}

        def normalize_time(ts: datetime):
            # Amber can return timestamps with a few extra seconds (e.g. xx:30:01).
            # Normalise to exact minute boundaries so 5-minute keys align correctly.
            return ts.replace(second=0, microsecond=0)

        def add_intervals(general_intervals, feed_in_intervals, time_offset=timedelta(0)):
            for general, feed_in in zip(general_intervals, feed_in_intervals):
                start_time = normalize_time(general.start_time) + time_offset
                end_time = normalize_time(general.end_time) + time_offset

                interval_minutes = int((end_time - start_time).total_seconds() // 60)
                steps = max(interval_minutes // 5, 0)

                for step in range(steps):
                    t = start_time + timedelta(minutes=step * 5)
                    general_points[t] = round(general.price)
                    feed_in_points[t] = round(feed_in.price)
                    demand_window_points[t] = bool(general.demand_window)

        add_intervals(general_price_forecast_30_min_data, feed_in_price_forecast_30_min_data)
        # Shift "past" intervals forward by one day so they fill the post-12h horizon.
        add_intervals(past_general_30_min_data, past_feed_in_30_min_data, time_offset=timedelta(days=1))

        # Overwrite with native 5-minute data where available
        for general, feed_in in zip(general_price_forecast_5_min_data, feed_in_price_forecast_5_min_data):
            point_time = normalize_time(general.start_time)
            general_points[point_time] = round(general.price)
            feed_in_points[point_time] = round(feed_in.price)
            demand_window_points[point_time] = bool(general.demand_window)

        ordered_times = sorted(general_points.keys()) # Get the timestamps in order so we can return lists of prices in the correct sequence.

        # Trim to the current time so we don't return extrapolated points that are in the past.
        current_time = datetime.now(self.local_tz if self.local_tz is not None else timezone.utc)
        current_5min_slot = current_time.replace(second=0, microsecond=0) - timedelta(minutes=current_time.minute % 5)
        ordered_times = [t for t in ordered_times if t >= current_5min_slot]

        general_price_extrapolated_forecast = [general_points[t] for t in ordered_times]
        feed_in_price_extrapolated_forecast = [feed_in_points[t] for t in ordered_times]
        demand_window_extrapolated_forecast = [demand_window_points[t] for t in ordered_times]

        # Return extended forecast
        return [general_price_extrapolated_forecast[:N_5min], feed_in_price_extrapolated_forecast[:N_5min], demand_window_extrapolated_forecast[:N_5min], ordered_times[:N_5min]]

    # Get the 5 min, 30 min and past prices and combine into a 5 minutely 'forecast' that extends past the 12 hr limit
    def get_extrapolated_forecast(self, hours, advanced_forecast = False): 
        N_30min = int(hours / (30/60)) # Number of 30 min segments requested
        N_5min = int(hours / (5/60))   # Number of 5 min segments requested

        amber_forecast_30min_intervals = (60//30)*12    # Get the max 12hr forecast
        amber_past_30min_intervals = max(N_30min - amber_forecast_30min_intervals, 0)  # Fill the rest of the sim with past prices
    
        # Get the 5 minutely price forecasts
        [general_price_forecast_5_min_data, feed_in_price_forecast_5_min_data] = self.get_forecast(next_intervals=60//5, resolution=5, advanced_forecast=advanced_forecast)

        # Get the 30 minutely forecast
        [general_price_forecast_30_min_data, feed_in_price_forecast_30_min_data] = self.get_forecast(next_intervals=amber_forecast_30min_intervals, resolution=30, advanced_forecast=advanced_forecast)

        # Getz the past prices to form the 2nd half of the 24hr forecast due to the 12hr limit on forecasts
        [past_general_30_min_data, past_feed_in_30_min_data] = self.get_past_prices(amber_past_30min_intervals, resolution=30)

        # Build a 5-minute forecast keyed by timestamps, then project onto an explicit
        # fixed-length 5-minute timeline so callers always receive exactly N_5min bins.
        general_points = {}
        feed_in_points = {}
        demand_window_points = {}

        def normalize_time(ts: datetime):
            # Amber can return timestamps with a few extra seconds (e.g. xx:30:01).
            # Normalise to exact minute boundaries so 5-minute keys align correctly.
            return ts.replace(second=0, microsecond=0)

        def add_intervals(intervals, points, time_offset=timedelta(0), demand_points=None):
            for interval in intervals:
                start_time = normalize_time(interval.start_time) + time_offset
                end_time = normalize_time(interval.end_time) + time_offset

                interval_minutes = int((end_time - start_time).total_seconds() // 60)
                steps = max(interval_minutes // 5, 0)

                for step in range(steps):
                    t = start_time + timedelta(minutes=step * 5)
                    points[t] = round(interval.price)
                    if demand_points is not None and self.demand_tarrif:
                        demand_points[t] = bool(interval.demand_window)

        # Seed from 30-minute and shifted-past data.
        add_intervals(general_price_forecast_30_min_data, general_points, demand_points=demand_window_points)
        add_intervals(feed_in_price_forecast_30_min_data, feed_in_points)
        add_intervals(past_general_30_min_data, general_points, time_offset=timedelta(days=1), demand_points=demand_window_points)
        add_intervals(past_feed_in_30_min_data, feed_in_points, time_offset=timedelta(days=1))

        # Overwrite with native 5-minute data where available.
        for interval in general_price_forecast_5_min_data:
            point_time = normalize_time(interval.start_time)
            general_points[point_time] = round(interval.price)
            if(self.demand_tarrif):
                demand_window_points[point_time] = bool(interval.demand_window)
        for interval in feed_in_price_forecast_5_min_data:
            point_time = normalize_time(interval.start_time)
            feed_in_points[point_time] = round(interval.price)

        # Build fixed timeline anchored to the current 5-minute slot.
        current_time = datetime.now(self.local_tz if self.local_tz is not None else timezone.utc)
        current_5min_slot = current_time.replace(second=0, microsecond=0) - timedelta(minutes=current_time.minute % 5)
        ordered_times = [current_5min_slot + timedelta(minutes=5 * i) for i in range(N_5min)]

        def fill_from_points(points, times, default_value):
            if len(points) == 0:
                return [default_value for _ in times], len(times)

            known_times = sorted(points.keys())
            idx = 0
            last_value = points[known_times[0]]
            missing_count = 0
            filled = []

            for t in times:
                while idx < len(known_times) and known_times[idx] <= t:
                    last_value = points[known_times[idx]]
                    idx += 1

                if t in points:
                    filled.append(points[t])
                elif idx == 0 and t < known_times[0]:
                    filled.append(default_value)
                    missing_count += 1
                else:
                    filled.append(last_value)
                    if t not in points:
                        missing_count += 1

            return filled, missing_count

        general_price_extrapolated_forecast, general_missing = fill_from_points(general_points, ordered_times, default_value=50)
        feed_in_price_extrapolated_forecast, feed_missing = fill_from_points(feed_in_points, ordered_times, default_value=0)
        demand_window_extrapolated_forecast, demand_missing = fill_from_points(demand_window_points, ordered_times, default_value=True)

        if general_missing or feed_missing or demand_missing:
            logger.warning(
                "Amber extrapolated forecast required gap fill over %s bins (general=%s, feed-in=%s, demand-window=%s).",
                N_5min,
                general_missing,
                feed_missing,
                demand_missing,
            )
            logger.warning("Missing points were filled with default values (general=50 c/kWh, feed-in=0 c/kWh, demand-window=True). This will impact MPC performance.")

        # Return extended forecast with guaranteed length.
        return [general_price_extrapolated_forecast, feed_in_price_extrapolated_forecast, demand_window_extrapolated_forecast, ordered_times]


    def get_current_prices(self):
        url = (f"{self.base}/sites/{self.site_id}/prices/current")

        response = self.send_request(url)
        
        if(response and len(response) >= 2):
            for i in response:
                if(i["channelType"] == "general"):
                    general_price = i["perKwh"]
                    estimate = i['estimate']
                elif(i["channelType"] == "feedIn"):
                    feed_in_price = -i["perKwh"]
                    estimate = estimate or i['estimate']

            return [general_price, feed_in_price, estimate]
        else:
            raise AmberAPIError("Failed to get current price data from Amber API")
        
    def get_data(self, partial_update=False, forecast_hrs=None):
        [general_price, feed_in_price, estimate] = self.get_current_prices()
        
        if(self.data == None or partial_update == False):
            [general_price_forecast, feed_in_price_forecast] = self.get_forecast(next_intervals=24, resolution=30)

            storted_general_forecast = general_price_forecast.copy()
            storted_general_forecast.sort(key=lambda x: x.price, reverse=True)

            storted_feed_in_forecast = feed_in_price_forecast.copy()
            storted_feed_in_forecast.sort(key=lambda x: x.price, reverse=True)
        else:
            general_price_forecast = self.data.general_12hr_forecast
            feed_in_price_forecast = self.data.feedIn_12hr_forecast
            storted_general_forecast = self.data.general_12hr_forecast_sorted
            storted_feed_in_forecast = self.data.feedIn_12hr_forecast_sorted

        if(estimate and self.data != None): # if prices are an estimate, just pass the old not estimated prices through
            general_price = self.data.general_price
            feed_in_price = self.data.feedIn_price

        if((not estimate and forecast_hrs != None) or self.data == None):
            [general_extrapolated_forecast, feedIn_extrapolated_forecast, demand_window_extrapolated_forecast, extrapolated_timestamps] = self.get_extrapolated_forecast(hours=forecast_hrs)
        else:
            general_extrapolated_forecast = self.data.general_extrapolated_forecast
            feedIn_extrapolated_forecast = self.data.feedIn_extrapolated_forecast
            demand_window_extrapolated_forecast = self.data.demand_window_extrapolated_forecast

        self.data = amber_data(
            demand_tarrif_price=self.demand_tarrif_price,
            general_price=round(general_price),
            feedIn_price=round(feed_in_price),
            prices_estimated=estimate,
            general_max_forecast_price=round(storted_general_forecast[0].price),
            feedIn_max_forecast_price=round(storted_feed_in_forecast[0].price),
            general_12hr_forecast=general_price_forecast,
            feedIn_12hr_forecast=feed_in_price_forecast,
            general_12hr_forecast_sorted=storted_general_forecast,
            feedIn_12hr_forecast_sorted=storted_feed_in_forecast,
            general_extrapolated_forecast=general_extrapolated_forecast,
            feedIn_extrapolated_forecast=feedIn_extrapolated_forecast,
            demand_window_extrapolated_forecast=demand_window_extrapolated_forecast
            )
        return self.data

'''      
from zoneinfo import ZoneInfo
HA_TZ = ZoneInfo("Australia/Brisbane")

amber = AmberAPI("", "", HA_TZ,7)
fg,ff = amber.get_forecast(30,30)
r = [[i.demand_window, i.start_time] for i in fg]

g,f,d,t = amber.get_extrapolated_forecast(24)

for i in range(len(g)):
    print(f"{d[i]} {g[i]} {t[i]}")
'''
'''
from api_token_secrets import HA_URL, HA_TOKEN, AMBER_API_TOKEN, SITE_ID
amber = AmberAPI(AMBER_API_TOKEN, SITE_ID, errors=True)
url = (f"{amber.base}/sites/{amber.site_id}/prices/current")

response = amber.send_request(url)
print(response)

[general_price, feed_in_price] = amber.get_current_prices()


#Get 12 hour forecast
[general_price_forecast, feed_in_price_forecast] = amber.get_forecast(next_intervals=24, resolution=30)

storted_feed_in_forecast = feed_in_price_forecast.copy()
storted_feed_in_forecast.sort(key=lambda x: x.price, reverse=True)

target_dispatch_price = storted_feed_in_forecast[max(round(hrs_of_discharge_available*2 - 1),0)].price

#print(storted_feed_in_forecast)


print(f"Current General Price: {round(general_price)} c/kWh")
print(f"Current FeedIn Price: {round(feed_in_price)} c/kWh")
print(f"Max Forecasted FeedIn Price: {round(storted_feed_in_forecast[0].price)} c/kWh")
print(f"Target Dispatch Price: {round(target_dispatch_price)} c/kWh")

'''
