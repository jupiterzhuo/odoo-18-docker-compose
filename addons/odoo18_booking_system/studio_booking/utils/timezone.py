# Copyright 2025
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

"""
Studio Booking timezone utilities. All studio times use GMT+7 (Asia/Bangkok).
Sessions are stored in UTC in the database; convert to/from local for display.
"""

import pytz

# GMT+7 - Studio's local timezone (Asia/Bangkok)
STUDIO_TZ = pytz.timezone("Asia/Bangkok")
UTC = pytz.UTC


def utc_to_studio_local(dt):
    """
    Convert naive UTC datetime to naive datetime in studio local (GMT+7).
    Input: datetime stored in DB (naive, UTC)
    Output: datetime in Bangkok time (naive, for display/formatting)
    """
    if not dt:
        return None
    utc_dt = UTC.localize(dt) if dt.tzinfo is None else dt
    local_dt = utc_dt.astimezone(STUDIO_TZ)
    return local_dt.replace(tzinfo=None)


def studio_local_to_utc(dt):
    """
    Convert naive datetime in studio local (GMT+7) to naive UTC for DB storage.
    Input: datetime in Bangkok time (naive)
    Output: datetime in UTC (naive, for DB)
    """
    if not dt:
        return None
    local_dt = STUDIO_TZ.localize(dt)
    utc_dt = local_dt.astimezone(UTC)
    return utc_dt.replace(tzinfo=None)


def utc_to_studio_local_str(dt, fmt="%Y-%m-%d %H:%M:%S"):
    """Format UTC datetime as studio local time string."""
    local = utc_to_studio_local(dt)
    return local.strftime(fmt) if local else ""


def utc_now():
    """Return current UTC time as naive datetime. Use for comparisons with DB datetimes (stored in UTC)."""
    from datetime import datetime

    return datetime.utcnow()


def studio_today():
    """Return today's date in GMT+7 (studio's business date)."""
    from datetime import datetime

    now_utc = datetime.utcnow()
    utc_dt = UTC.localize(now_utc)
    local_dt = utc_dt.astimezone(STUDIO_TZ)
    return local_dt.date()


def date_to_utc_range(target_date):
    """
    Given a date in studio local (GMT+7), return (utc_start, utc_end) for that day.
    Use for DB queries: session_start >= utc_start AND session_start < utc_end.
    """
    from datetime import datetime, timedelta

    if not target_date:
        return None, None
    local_start = datetime.combine(target_date, datetime.min.time())
    local_end = local_start + timedelta(days=1)
    utc_start = studio_local_to_utc(local_start)
    utc_end = studio_local_to_utc(local_end)
    return utc_start, utc_end
