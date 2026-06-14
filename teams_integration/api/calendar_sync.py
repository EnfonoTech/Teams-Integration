# Copyright (c) 2026, siva@enfono.com
# Feature 6: Two-way Outlook ↔ ERPNext Calendar Sync

import frappe
import requests
from datetime import datetime, timedelta
from .helpers import get_access_token, GRAPH_API


# ---------------------------------------------------------------------------
# Outlook → ERPNext (import)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def sync_outlook_to_erpnext(days_ahead=30):
    """
    Fetch upcoming Outlook calendar events and create or update matching ERPNext Events.

    Deduplication key: custom_outlook_event_id on the ERPNext Event doctype.
    Existing ERPNext events that were originally pushed TO Outlook are updated in-place.
    Events created externally in Outlook are created fresh in ERPNext.
    """
    token = get_access_token()
    if not token:
        return {"error": "auth_required"}

    now = datetime.utcnow()
    to_date = now + timedelta(days=int(days_ahead))
    from_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    to_str = to_date.strftime("%Y-%m-%dT%H:%M:%SZ")

    url = (
        f"{GRAPH_API}/me/events"
        f"?$filter=start/dateTime ge '{from_str}' and start/dateTime le '{to_str}'"
        f"&$orderby=start/dateTime"
        f"&$top=100"
        f"&$select=id,subject,start,end,bodyPreview,onlineMeeting,isCancelled,attendees,isAllDay"
    )

    try:
        res = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    except requests.exceptions.Timeout:
        frappe.throw("Calendar sync timed out. Please try again.")

    if res.status_code != 200:
        frappe.log_error(
            f"Outlook calendar fetch failed: {res.status_code} - {res.text}",
            "Teams Calendar Sync Error",
        )
        frappe.throw(f"Failed to fetch Outlook calendar: {res.status_code}")

    events = res.json().get("value", [])
    created = updated = skipped = 0

    for event in events:
        outlook_id = event.get("id")
        if not outlook_id:
            continue

        if event.get("isCancelled"):
            skipped += 1
            continue

        subject = event.get("subject") or "Outlook Event"
        start_raw = (event.get("start") or {}).get("dateTime")
        end_raw = (event.get("end") or {}).get("dateTime")
        join_url = ((event.get("onlineMeeting") or {}).get("joinUrl")) or ""
        description = event.get("bodyPreview", "")[:500]
        all_day = event.get("isAllDay", False)

        existing = frappe.db.get_value("Event", {"custom_outlook_event_id": outlook_id}, "name")

        try:
            if existing:
                frappe.db.set_value("Event", existing, {
                    "subject": subject,
                    "starts_on": start_raw,
                    "ends_on": end_raw,
                    "custom_teams_meeting_url": join_url,
                })
                updated += 1
            else:
                new_event = frappe.get_doc({
                    "doctype": "Event",
                    "subject": subject,
                    "starts_on": start_raw,
                    "ends_on": end_raw,
                    "custom_outlook_event_id": outlook_id,
                    "custom_teams_meeting_url": join_url,
                    "description": description,
                    "event_type": "Private",
                    "all_day": all_day,
                })
                new_event.insert(ignore_permissions=True)
                created += 1
        except Exception as e:
            frappe.log_error(
                f"Error syncing Outlook event {outlook_id}: {str(e)}", "Teams Calendar Import Error"
            )
            skipped += 1

    frappe.db.commit()
    return {
        "success": True,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "total": len(events),
    }


# ---------------------------------------------------------------------------
# ERPNext → Outlook (push single event)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def push_event_to_outlook(event_name):
    """
    Push an existing ERPNext Event to Outlook Calendar if it doesn't already have
    an Outlook Event ID. Use 'Create Teams Meeting' on the Event form instead
    if you want a Teams meeting link too.
    """
    doc = frappe.get_doc("Event", event_name)

    if doc.custom_outlook_event_id:
        return {"success": True, "message": "Already synced to Outlook.", "outlook_id": doc.custom_outlook_event_id}

    token = get_access_token()
    if not token:
        return {"error": "auth_required"}

    subject = doc.subject or f"Event: {event_name}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    from .meetings import to_utc_isoformat, _build_event_attendees
    from frappe.utils import get_datetime

    starts_on = get_datetime(doc.starts_on)
    ends_on = get_datetime(doc.ends_on) if doc.ends_on else (starts_on + timedelta(hours=1))

    attendee_emails = [
        row.email for row in (doc.event_participants or []) if getattr(row, "email", None)
    ]

    payload = {
        "subject": subject,
        "start": {"dateTime": to_utc_isoformat(starts_on), "timeZone": "UTC"},
        "end": {"dateTime": to_utc_isoformat(ends_on), "timeZone": "UTC"},
        "attendees": _build_event_attendees(attendee_emails),
        "isOnlineMeeting": False,
    }

    try:
        res = requests.post(f"{GRAPH_API}/me/events", headers=headers, json=payload, timeout=30)
    except requests.exceptions.Timeout:
        frappe.throw("Request timed out.")

    if res.status_code in (200, 201):
        data = res.json()
        doc.db_set("custom_outlook_event_id", data.get("id"))
        frappe.db.commit()
        return {"success": True, "message": "Event pushed to Outlook Calendar.", "outlook_id": data.get("id")}

    frappe.throw(f"Failed to push to Outlook: {res.status_code}")


# ---------------------------------------------------------------------------
# Scheduled daily sync
# ---------------------------------------------------------------------------

def daily_calendar_sync():
    """Scheduled daily task: import the next 30 days of Outlook events into ERPNext."""
    try:
        result = sync_outlook_to_erpnext(days_ahead=30)
        frappe.log_error(
            f"Daily calendar sync: {result}", "Teams Calendar Sync Daily"
        )
    except Exception as e:
        frappe.log_error(str(e), "Teams Calendar Sync Daily Error")
