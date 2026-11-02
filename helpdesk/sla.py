"""SLA rules, kept apart from the models so they are easy to read and to test.

Each priority has two targets, measured from when the ticket was raised:
  - first response: an IT staff member replies to the requester
  - resolution: the ticket is marked Resolved

Times are calendar hours (24/7). Business hours and pausing the clock while waiting
on the requester are not modelled; see the README.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class SlaTarget:
    response: timedelta
    resolution: timedelta


# Keyed by Ticket.Priority value (1 = P1 Critical ... 4 = P4 Low).
SLA_TARGETS = {
    1: SlaTarget(response=timedelta(minutes=30), resolution=timedelta(hours=4)),
    2: SlaTarget(response=timedelta(hours=1), resolution=timedelta(hours=8)),
    3: SlaTarget(response=timedelta(hours=4), resolution=timedelta(hours=24)),
    4: SlaTarget(response=timedelta(hours=8), resolution=timedelta(hours=72)),
}

# A running timer is "at risk" when less than this share of its time is left.
AT_RISK_SHARE = 0.25

ON_TRACK = "on_track"
AT_RISK = "at_risk"
BREACHED = "breached"
MET = "met"

STATE_LABELS = {
    ON_TRACK: "On track",
    AT_RISK: "At risk",
    BREACHED: "Breached",
    MET: "Met",
}


def due_dates(priority: int, start: datetime) -> tuple[datetime, datetime]:
    """(first response due, resolution due) for a ticket raised at `start`."""
    target = SLA_TARGETS[priority]
    return start + target.response, start + target.resolution


def sla_state(start: datetime, due: datetime, done_at: datetime | None, now: datetime) -> str:
    """Where one SLA timer stands.

    Finished timers are MET or BREACHED. Running timers are BREACHED once past due,
    AT_RISK in the last quarter of their time, otherwise ON_TRACK.
    """
    if done_at is not None:
        return MET if done_at <= due else BREACHED
    if now >= due:
        return BREACHED
    if (due - now) <= (due - start) * AT_RISK_SHARE:
        return AT_RISK
    return ON_TRACK


def describe_time_left(due: datetime, now: datetime) -> str:
    """'2h 15m left' or 'overdue by 1d 3h', for showing next to a timer."""
    delta = due - now
    overdue = delta.total_seconds() < 0
    minutes = int(abs(delta.total_seconds()) // 60)
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    if days:
        text = f"{days}d {hours}h"
    elif hours:
        text = f"{hours}h {minutes}m"
    else:
        text = f"{minutes}m"
    return f"overdue by {text}" if overdue else f"{text} left"
