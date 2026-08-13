# This file is used to manipulate and manage data from HA entities. 
import datetime
import pandas as pd
from dataclasses import dataclass
from typing import Any, List, Union, Tuple, Optional

@dataclass
class BinnedStateClass:
    """A single time-binned historical sample with the raw values and the aggregated value."""
    states: list[Any]
    avg_state: Any
    time: datetime.datetime


def round_minutes(value: datetime.datetime, nearest_minute: int) -> datetime.datetime:
    """Round a datetime down to the nearest minute boundary."""
    return value.replace(
        minute=(value.minute // nearest_minute) * nearest_minute,
        second=0,
        microsecond=0,
    )


def approx_equal(a: float, b: float, threshold: float = 0.2) -> bool:
    """Return True when the two numeric values differ by less than the threshold."""
    return abs(a - b) < threshold


def bin_data(
    history: list[Any],
    bin_period: int,
    start_bin_datetime: datetime.datetime,
    end_bin_datetime: datetime.datetime,
    string_state: bool = False,
    interpolation_method: str = "linear",
) -> list[BinnedStateClass]:
    """Bin historical data into fixed time windows and optionally interpolate missing values.

    history[x].state    -> numeric value (string or float)
    history[x].time     -> datetime object (tz-aware)
    start_bin_datetime  -> datetime object for bin start time
    end_bin_datetime    -> datetime object for bin end time
    bin_period          -> time period (minutes) to bin data into

    Returns:
        List of BinnedStateClass objs:
        [
            bin.time": bin_start_datetime,
            bin.avg_state": average_value_in_bin
            ...
        ]
    """
    bin_delta = datetime.timedelta(minutes=bin_period)
    if end_bin_datetime < start_bin_datetime:
        raise ValueError(f"end_bin_datetime: '{end_bin_datetime}' must be greater than or equal to start_bin_datetime: '{start_bin_datetime}'")
    bin_qty = int(((end_bin_datetime - start_bin_datetime).total_seconds()) // bin_delta.total_seconds()) + 1

    # Remove any invalid states from the history list (Unavailable, None, etc)
    clean_history = []
    for hist in history:
        try:
            if hist.state is not None:
                if not string_state:
                    hist.state = float(hist.state)
                clean_history.append(hist)
        except (ValueError, TypeError):
            pass  # drop unknown/unavailable/etc
            

    binned_history = []
    current_bin_datetime = start_bin_datetime

    # Build the binned history skeleton with empty states and correct time bins
    for i in range(bin_qty):
        binned_history.append(BinnedStateClass(avg_state=None, states=[], time=current_bin_datetime))
        current_bin_datetime = current_bin_datetime + bin_delta
    
    i = 0 # Incrementer for binned_history
    for state in clean_history:
        delta = state.time - start_bin_datetime # Time delta between start bin time and current state time
        bin_index = int(delta.total_seconds() // bin_delta.total_seconds())
        #print(f"Delta{delta}  idx:{bin_index} binqty:{bin_qty}")

        if 0 <= bin_index < bin_qty:
            binned_history[bin_index].states.append(state.state)

    #for interval in binned_history: # Print for debuging
    #    print(interval.states)

    if not string_state: # If the state is a string, don't try an average it
        for interval in binned_history:
            if(len(interval.states) == 0):
                interval.avg_state = None
                #raise Exception(f"Failed to get state data for {interval.time} time period")
            else:
                interval.avg_state = round(sum(interval.states) / len(interval.states), 2)
        
        # Interpolation
        values = [b.avg_state for b in binned_history]
        values = interpolate_values(values, method=interpolation_method)  
        for i, interval in enumerate(binned_history):
            interval.avg_state = round(values[i], 2)

    else: # If the state is a string
        last_known_state = "Unknown"
        if(binned_history[0].states):
            last_known_state = binned_history[0].states[-1]

        for bin in binned_history:
            if(bin.states):
                bin.avg_state = bin.states[-1]
                last_known_state = bin.states[-1]
            else:
                bin.avg_state = last_known_state # If there is no state update in the binned time, the state mustn't have changed so use the last known value

        #print(f"avg: {interval.state} states: {interval.states}")

    #for i in range(len(avg_day)): # Print average for each day and each time
    #    print(avg_day[i].state)
    #    print(avg_day[i].states)       

    return binned_history

def interpolate_values(values: List[Optional[float]], method: str = "linear") -> List[float]:
    """Interpolate missing numeric values while preserving the list length."""
    s = pd.Series(values)
    # Ensure the series is numeric to avoid "Series cannot interpolate with object dtype" 
    # which occurs when the list contains only None values or mixed types.
    s = pd.to_numeric(s, errors='coerce')

    if method == "linear":
        # 5, None, None, None, 6 → 5, 5.25, 5.5, 5.75, 6
        return (
            s.interpolate(method="linear")
            .bfill()
            .ffill()
            .tolist()
        )

    elif method == "step":
        # 5, None, None, None, 6 → 5, 5, 5, 5, 6
        return (
            s.ffill()   # forward fill
            .bfill()   # in case the first values are None
            .tolist()
        )

    else:
        raise ValueError("method must be 'linear' or 'step'")
    

def get_time_range_from_hours(hours: float, tz: datetime.tzinfo) -> Tuple[datetime.datetime, datetime.datetime]:
    """
    Converts a duration in hours into a start and end datetime pair, 
    rounded to the nearest 5-minute interval.
    """
    from datetime import datetime, timedelta

    now = datetime.now(tz)
    rounded_now = round_minutes(time=now, nearest_minute=5)
    start_datetime = round_minutes(time=rounded_now - timedelta(hours=hours), nearest_minute=5)
    end_datetime = rounded_now
    
    return start_datetime, end_datetime