#!/usr/bin/env python3
"""Advance active state and ask the owner to confirm newly-past items."""
import json
import subprocess
import datetime as dt
import hashlib
from zoneinfo import ZoneInfo

SECOND_BRAIN = "__OPENCLAW_HOME__/.openclaw/workspace-personal/skills/second-brain/scripts/second_brain.py"
OPENCLAW = "__OPENCLAW_HOME__/.openclaw/bin/openclaw"
TARGET = "user:__OWNER_DISCORD_ID__"
LOCAL_TZ = ZoneInfo("America/Vancouver")
RECONCILIATION_GRACE = dt.timedelta(minutes=10)

def parse_moment(value):
    if not value: return None
    moment = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None: moment = moment.replace(tzinfo=LOCAL_TZ)
    return moment.astimezone(dt.timezone.utc)

def checkin_target(record):
    return parse_moment(record.get("checkin_at") or record.get("ends_at") or
                        record.get("starts_at") or record.get("due_at") or record.get("review_at"))

def natural_time(value):
    if not value or value == "its scheduled time": return "its scheduled time"
    moment = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None: moment = moment.replace(tzinfo=LOCAL_TZ)
    moment = moment.astimezone(LOCAL_TZ)
    today = dt.datetime.now(LOCAL_TZ).date()
    delta = (moment.date() - today).days
    hour = moment.strftime("%I").lstrip("0")
    clock = f"{hour} {moment.strftime('%p')}" if moment.minute == 0 else f"{hour}:{moment.strftime('%M')} {moment.strftime('%p')}"
    if delta == 0: return f"{clock} today"
    if delta == -1: return f"{clock} yesterday"
    if -6 <= delta <= 6: return f"{moment.strftime('%A')} at {clock}"
    year = f", {moment.year}" if moment.year != today.year else ""
    return f"{moment.strftime('%B')} {moment.day}{year} at {clock}"

def main():
    tick = subprocess.run(
        ["/usr/bin/python3", SECOND_BRAIN, "active-tick", "--imminent-hours", "72"],
        check=True, capture_output=True, text=True,
    )
    item = subprocess.run(
        ["/usr/bin/python3", SECOND_BRAIN, "active-list", "--historical", "--limit", "100"],
        check=True, capture_output=True, text=True,
    )
    current = dt.datetime.now(dt.timezone.utc)
    pending = [x for x in json.loads(item.stdout)["items"]
               if x["status"] == "awaiting_confirmation" and not x.get("checkin_sent_at")
               and checkin_target(x) is not None
               and current >= checkin_target(x) + RECONCILIATION_GRACE]
    if not pending:
        return

    item_blocks = []
    for index, record in enumerate(pending, start=1):
        when = natural_time(record.get("starts_at") or record.get("due_at") or "its scheduled time")
        item_blocks.append(
            f"Item {index}:\n"
            f"Title: {record['title']}\n"
            f"Context: {record.get('summary') or 'No additional context'}\n"
            f"Scheduled time: {when}\n"
            f"Check-in rationale: {record.get('checkin_reason') or 'Its expected completion time passed'}"
        )

    prompt = (
        "Write one short, natural Discord check-in to __OWNER_NAME__ covering every past scheduled item below. "
        "Send a single cohesive message, not one message per item. Let the details determine the phrasing and order. "
        "It may use a couple of conversational sentences when that sounds natural, but it must not look like a form, "
        "notification template, or database report. Ask whether each item happened or how it went without offering a "
        "mechanical list of statuses. Do not repeat 'Hey __OWNER_NAME__' for each item. No Markdown, bold text, headings, bullets, "
        "status labels, timestamps, metadata, or explanation. Do not call tools. Output only the message to send.\n\n"
        + "\n\n".join(item_blocks)
    )
    batch_key = hashlib.sha256("\n".join(sorted(x["id"] for x in pending)).encode()).hexdigest()[:16]
    subprocess.run([
        OPENCLAW, "agent", "--agent", "main",
        "--session-key", f"agent:main:active-checkin-batch:{batch_key}",
        "--message", prompt, "--thinking", "low", "--deliver",
        "--reply-channel", "discord", "--reply-to", TARGET,
    ], check=True, timeout=180)
    subprocess.run(
        ["/usr/bin/python3", SECOND_BRAIN, "active-notified", "--ids", *[record["id"] for record in pending]],
        check=True,
    )

if __name__ == "__main__": main()
