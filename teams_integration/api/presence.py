# Copyright (c) 2026, siva@enfono.com
# Feature 3: Microsoft Teams Presence Status

import frappe
import requests
from .helpers import get_access_token, GRAPH_API

# Availability → display label + CSS colour class mapping
_AVAILABILITY_MAP = {
    "Available": ("Available", "green"),
    "AvailableIdle": ("Available (Idle)", "green"),
    "Away": ("Away", "yellow"),
    "BeRightBack": ("Be Right Back", "yellow"),
    "Busy": ("Busy", "red"),
    "BusyIdle": ("Busy (Idle)", "red"),
    "DoNotDisturb": ("Do Not Disturb", "red"),
    "Offline": ("Offline", "grey"),
    "PresenceUnknown": ("Unknown", "grey"),
}


@frappe.whitelist()
def get_employee_presence(employee_name):
    """
    Get the Microsoft Teams presence status for a specific employee.

    Requires the 'Presence.Read.All' delegated permission on the Azure app.
    If the permission is missing, a 403 is returned and the status will be 'Unknown'.
    """
    azure_id = frappe.db.get_value("Employee", employee_name, "azure_object_id")
    if not azure_id:
        return {"availability": "Unknown", "label": "No Azure ID", "colour": "grey"}

    token = get_access_token()
    if not token:
        return {"availability": "Unknown", "label": "Not Authenticated", "colour": "grey"}

    try:
        res = requests.get(
            f"{GRAPH_API}/users/{azure_id}/presence",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if res.status_code == 200:
            data = res.json()
            availability = data.get("availability", "PresenceUnknown")
            label, colour = _AVAILABILITY_MAP.get(availability, ("Unknown", "grey"))
            return {
                "availability": availability,
                "label": label,
                "colour": colour,
                "activity": data.get("activity"),
            }
        if res.status_code == 403:
            return {
                "availability": "Unknown",
                "label": "Presence.Read.All permission required",
                "colour": "grey",
            }
        frappe.log_error(
            f"Presence fetch failed for {employee_name}: {res.status_code}",
            "Teams Presence Error",
        )
        return {"availability": "Unknown", "label": f"Error {res.status_code}", "colour": "grey"}

    except Exception as e:
        frappe.log_error(str(e), "Teams Presence Error")
        return {"availability": "Unknown", "label": "Error", "colour": "grey"}


@frappe.whitelist()
def get_bulk_presence(employee_names):
    """
    Fetch Teams presence for multiple employees in one Graph batch call.
    employee_names: JSON list of Employee names.
    Returns a dict keyed by employee_name.
    """
    import json as _json

    if isinstance(employee_names, str):
        employee_names = _json.loads(employee_names)

    token = get_access_token()
    if not token:
        return {}

    # Collect azure_ids
    id_map = {}  # azure_id → employee_name
    for emp_name in employee_names:
        azure_id = frappe.db.get_value("Employee", emp_name, "azure_object_id")
        if azure_id:
            id_map[azure_id] = emp_name

    if not id_map:
        return {}

    try:
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {"ids": list(id_map.keys())}
        res = requests.post(
            f"{GRAPH_API}/communications/getPresencesByUserId",
            headers=headers,
            json=payload,
            timeout=20,
        )

        if res.status_code != 200:
            frappe.log_error(
                f"Bulk presence failed: {res.status_code} - {res.text}", "Teams Bulk Presence Error"
            )
            return {}

        result = {}
        for item in res.json().get("value", []):
            azure_id = item.get("id")
            emp_name = id_map.get(azure_id)
            if emp_name:
                availability = item.get("availability", "PresenceUnknown")
                label, colour = _AVAILABILITY_MAP.get(availability, ("Unknown", "grey"))
                result[emp_name] = {
                    "availability": availability,
                    "label": label,
                    "colour": colour,
                    "activity": item.get("activity"),
                }
        return result

    except Exception as e:
        frappe.log_error(str(e), "Teams Bulk Presence Error")
        return {}
