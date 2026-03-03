from urllib.parse import urlparse
from datetime import datetime, date, time, timezone, timedelta

from caldav import DAVClient
from caldav.elements import ical

from . import VERSION

USER_AGENT = "CalCleaner/%s" % VERSION


def _to_naive_utc(value):
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, time.min)
    if value.tzinfo:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _event_is_older_than(event, threshold):
    vevent = getattr(event.vobject_instance, "vevent", None)
    if not vevent:
        return False

    dtend = getattr(vevent, "dtend", None)
    dtstart = getattr(vevent, "dtstart", None)
    event_date = (dtend or dtstart)
    if not event_date:
        return False

    try:
        event_dt = _to_naive_utc(event_date.value)
    except Exception:
        return False
    return event_dt < threshold


def fetch_calendars(url, username, password, verify_cert=True):
    with DAVClient(
        url, username=username, password=password, ssl_verify_cert=verify_cert
    ) as dav_client:
        dav_client.headers["User-Agent"] = USER_AGENT
        dav_principal = dav_client.principal()
        for calendar in dav_principal.calendars():
            color = calendar.get_properties([ical.CalendarColor()]).get(
                "{http://apple.com/ns/ical/}calendar-color", "#888888"
            )
            yield {
                "url": calendar.canonical_url,
                "name": calendar.name,
                "color": color,
                "event_count": len(calendar.events()),
            }


def clean_calendar(
    url,
    username,
    password,
    verify_cert=True,
    max_age=16,
    keep_recurring_events=True,
):
    """Purge old events of given calendar.

    :param str url: The exactu URL of the calendar to clean (not the DAV principal URL).
    :param str username: The username of the CalDAV account.
    :param str password: The password of the CalDAV account.
    :param bool verify_cert: Enable or disable SSL certificate verification (to
                             allow self signed certificates)
    :param int max_age: The maximum age of events to keep (in weeks). All
                        events older than the given age will be deleted.
    :param bool keep_recurring_events: If true, recurring events will be skipped.

    :rtype: Generator<tuple>
    :return: ``(cleaned_count, to_clean_clount)``
    """
    start_date = datetime(year=1900, month=1, day=1)
    end_date = datetime.now() - timedelta(weeks=max_age)

    with DAVClient(
        url, username=username, password=password, ssl_verify_cert=verify_cert
    ) as dav_client:
        dav_client.headers["User-Agent"] = USER_AGENT
        dav_principal = dav_client.principal()
        old_events = None

        for calendar in dav_principal.calendars():
            if calendar.canonical_url == url:
                try:
                    old_events = calendar.date_search(start=start_date, end=end_date)
                except Exception as error:
                    if "Expected a valid recurrence set" not in str(error):
                        raise
                    print(
                        "Calendar '%s': fallback to non-recurring search due to malformed recurrence set."
                        % url
                    )
                    old_events = [
                        event
                        for event in calendar.events()
                        if _event_is_older_than(event, end_date)
                    ]
                break

        if old_events:
            cleaned_count = 0
            for event in old_events:
                cleaned_count += 1
                if (
                    hasattr(event.vobject_instance, "vevent")
                    and hasattr(event.vobject_instance.vevent, "recurrence_id")
                    and keep_recurring_events
                ):
                    print(
                        "Skipped a recurring event: '%s'"
                        % event.vobject_instance.vevent.summary.value
                    )
                else:
                    event.delete()
                yield (cleaned_count, len(old_events))
        else:
            yield (0, 0)


def readable_account_url(url, username):
    return "@".join([username, urlparse(url).netloc])
