import datetime

def round_minutes(time: datetime.datetime, nearest_minute: int) -> datetime.datetime:
    return time.replace(
        minute=(time.minute // nearest_minute) * nearest_minute,
        second=0,
        microsecond=0
        )  