import requests
import time
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class PriceForecast:
    price: float
    start_time: datetime
    end_time: datetime

@dataclass
class amber_data:
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
    


UTC_OFFSET = timedelta(hours=10) #UTC time, +10 for Brisbane

# 1) Get your site list
#sites = amber.get_sites()
#print("Your sites:", sites)

kwh_of_discharge_available = 15
max_discharge_rate = 15
hrs_of_discharge_available = kwh_of_discharge_available/max_discharge_rate

class AmberAPI:
    def __init__(self, api_key, site_id, errors):
        self.api_key = api_key
        self.site_id = site_id
        self.base = "https://api.amber.com.au/v1"

        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json"
        }
        self.errors = errors
        self.rate_limit_remaining = None
        self.seconds_till_rate_limit_reset = None
        self.data = None
    
    def send_request(self, url):
        r = requests.get(url, headers=self.headers)
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

        # Check for rate limiting
        if r.status_code == 429:

            if self.seconds_till_rate_limit_reset:
                logger.error(f"Exceeded Amber API request rate limit.")
                logger.error(f"Waiting {self.seconds_till_rate_limit_reset+5} seconds before retrying")
                time.sleep(int(self.seconds_till_rate_limit_reset+5))
            else:
                logger.error(r.headers)
                logger.error(f"Exceeded AmazonAWS Amber API request rate limit.")
                logger.error(f"Waiting 10 seconds before retrying")
                time.sleep(10)
            return self.send_request(url)
        
        return r.json()

    def get_sites(self):
        """Return all sites linked to your Amber account."""
        url = f"{self.base}/sites"
        return self.send_request(url)
    
    def get_past_prices(self, previous_intervals, resolution):
        """Return 12 hours of prices before now for a given site."""
        if(resolution != 30 and resolution != 5):
            if(self.errors):
                raise("Resolution must be 5 or 30 minutes not: "+str(resolution))

        url = (f"{self.base}/sites/{self.site_id}/prices/current?next=0&previous={previous_intervals}&resolution={resolution}")

        previous_general_prices = []
        previous_feed_in_price = []
        date_format = "%Y-%m-%dT%H:%M:%SZ"

        response = self.send_request(url)
        if(len(response) >= 2):
            for i in response:
                start = datetime.strptime(i["startTime"], date_format) + UTC_OFFSET
                end   = datetime.strptime(i["endTime"], date_format) + UTC_OFFSET

                if i["channelType"] == "general":
                    price = i["perKwh"]   
                    interval = PriceForecast(price=price, start_time=start, end_time=end)
                    previous_general_prices.append(interval)

                elif i["channelType"] == "feedIn":
                    price = -i["perKwh"]   
                    interval = PriceForecast(price=price, start_time=start, end_time=end)
                    previous_feed_in_price.append(interval)

        return [previous_general_prices, previous_feed_in_price]
        
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
        if(len(response) >= 2):
            for i in response:
                start = datetime.strptime(i["startTime"], date_format) + UTC_OFFSET
                end   = datetime.strptime(i["endTime"], date_format) + UTC_OFFSET

                if i["channelType"] == "general":
                    if("advancedPrice" in i and advanced_forecast == True):
                        price = i["advancedPrice"]["predicted"]
                    else:
                        price = i["perKwh"]   
                    interval = PriceForecast(price=price, start_time=start, end_time=end)
                    general_price_forecast.append(interval)

                elif i["channelType"] == "feedIn":
                    if("advancedPrice" in i and advanced_forecast == True):
                        price = -i["advancedPrice"]["predicted"]
                    else:
                        price = -i["perKwh"]    
                    interval = PriceForecast(price=price, start_time=start, end_time=end)
                    feed_in_price_forecast.append(interval)

        return [general_price_forecast, feed_in_price_forecast]
    
    # Get the 5 min, 30 min and past prices and combine into a 5 minutely 'forecast' that extends past the 12 hr limit
    def get_extrapolated_forecast(self, hours, advanced_forecast = False): 
        steps_per_price = 30 // 5 # = 6
        N_30min = int(hours / (30/60)) # Number of 30 min segments requested
        N_5min = int(hours / (5/60))   # Number of 5 min segments requested

        amber_forecast_30min_intervals = (60//30)*12    # Get the max 12hr forecast
        amber_past_30min_intervals = max(N_30min - amber_forecast_30min_intervals, 0)  # Fill the rest of the sim with past prices
    
        # Get the 5 minutely price forecasts
        [general_price_forecast_5_min, feed_in_price_forecast_5_min] = self.get_forecast(next_intervals=60//5, resolution=5, advanced_forecast=advanced_forecast)
        feed_in_price_forecast_5_min = [round(feedIn.price) for feedIn in feed_in_price_forecast_5_min][0:11] # select only the first 12 forecast intervals (1 hr)
        general_price_forecast_5_min = [round(general.price) for general in general_price_forecast_5_min][0:11]

        # Get the 30 minutely forecast
        [general_price_forecast_30_min, feed_in_price_forecast_30_min] = self.get_forecast(next_intervals=amber_forecast_30min_intervals, resolution=30, advanced_forecast=advanced_forecast)
        general_price_forecast_30_min = [round(pf.price) for pf in general_price_forecast_30_min]
        feed_in_price_forecast_30_min = [round(pf.price) for pf in feed_in_price_forecast_30_min]
        general_price_forecast_30_min_expanded = np.repeat(general_price_forecast_30_min,  steps_per_price)
        feed_in_price_forecast_30_min_expanded = np.repeat(feed_in_price_forecast_30_min, steps_per_price)


        # Get the past prices to form the 2nd half of the 24hr forecast due to the 12hr limit on forecasts
        [past_general_5_min, past_feed_in_5_min] = self.get_past_prices(amber_past_30min_intervals, resolution=30)
        past_general_prices_5_min = [round(pf.price) for pf in past_general_5_min] # Extract the price and round it from the forecasts
        past_feed_in_prices_5_min = [round(pf.price) for pf in past_feed_in_5_min]
        past_general_prices_5_min = np.repeat(past_general_prices_5_min,  steps_per_price) # Expand the prices out to 5 minutely
        past_feed_in_prices_5_min = np.repeat(past_feed_in_prices_5_min,  steps_per_price)


        general_price_forecast = np.append(general_price_forecast_30_min_expanded, past_general_prices_5_min) # append the past prices to the 12hr forecast to allow for a 24hr prediction
        feed_in_price_forecast = np.append(feed_in_price_forecast_30_min_expanded, past_feed_in_prices_5_min)

        feed_in_price_forecast[0:len(feed_in_price_forecast_5_min)] = feed_in_price_forecast_5_min
        general_price_forecast[0:len(general_price_forecast_5_min)] = general_price_forecast_5_min

        # Return extended forecast
        return [general_price_forecast[:N_5min], feed_in_price_forecast[:N_5min]]

    def get_current_prices(self):
        url = (f"{self.base}/sites/{self.site_id}/prices/current")

        response = self.send_request(url)
        if(len(response) >= 2):
            for i in response:
                if(i["channelType"] == "general"):
                    general_price = i["perKwh"]
                    estimate = i['estimate']
                elif(i["channelType"] == "feedIn"):
                    feed_in_price = -i["perKwh"]
                    estimate = estimate or i['estimate']

        return [general_price, feed_in_price, estimate]
    
    def get_data(self, partial_update=False, forecast_hrs=None):
        [general_price, feed_in_price, estimate] = self.get_current_prices()
        
        if(self.data == None or partial_update == False):
            [general_price_forecast, feed_in_price_forecast] = self.get_forecast(next_intervals=24, resolution=30)

            storted_general_forecast = feed_in_price_forecast.copy()
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
            [general_extrapolated_forecast, feedIn_extrapolated_forecast] = self.get_extrapolated_forecast(hours=forecast_hrs)
        else:
            general_extrapolated_forecast = self.data.general_extrapolated_forecast
            feedIn_extrapolated_forecast = self.data.feedIn_extrapolated_forecast

        self.data = amber_data(
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
            feedIn_extrapolated_forecast=feedIn_extrapolated_forecast
            )
        return self.data
      

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
