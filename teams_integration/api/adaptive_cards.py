# Copyright (c) 2026, siva@enfono.com
# Feature 2: Adaptive Cards — rich interactive messages in Microsoft Teams

import frappe
import requests
import uuid
from .helpers import get_access_token, GRAPH_API


def _send_card_to_chat(chat_id, card_json, docname=None, doctype=None):
    """Send an Adaptive Card as a message to a Teams chat."""
    token = get_access_token()
    if not token:
        return {"error": "auth_required"}

    attachment_id = str(uuid.uuid4()).replace("-", "")
    import json as _json

    payload = {
        "body": {
            "contentType": "html",
            "content": f'<attachment id="{attachment_id}"></attachment>',
        },
        "attachments": [
            {
                "id": attachment_id,
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": _json.dumps(card_json),
            }
        ],
    }

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    res = requests.post(
        f"{GRAPH_API}/chats/{chat_id}/messages", headers=headers, json=payload, timeout=30
    )

    if res.status_code in (200, 201):
        from .chat import _save_message_local
        _save_message_local(res.json(), chat_id, docname, doctype, "Outbound")
        return {"success": True, "message_id": res.json().get("id")}

    frappe.log_error(
        f"Adaptive Card send failed: {res.status_code} - {res.text}", "Teams Adaptive Card Error"
    )
    frappe.throw(f"Failed to send adaptive card: {res.status_code}")


def _doc_url(doctype, docname):
    return f"{frappe.utils.get_url()}/app/{frappe.utils.scrub(doctype)}/{frappe.utils.quote(docname)}"


# ---------------------------------------------------------------------------
# Card templates
# ---------------------------------------------------------------------------

@frappe.whitelist()
def send_approval_card(chat_id, doctype, docname, note=None):
    """
    Send an approval request card to a Teams chat.
    Recipients can click 'Open & Approve' to go directly to the ERPNext document.
    """
    if not chat_id or not doctype or not docname:
        frappe.throw("chat_id, doctype, and docname are required")

    requester = frappe.utils.get_fullname(frappe.session.user)
    doc_url = _doc_url(doctype, docname)

    facts = [
        {"title": "Document", "value": f"{doctype}: **{docname}**"},
        {"title": "Requested by", "value": requester},
    ]
    if note:
        facts.append({"title": "Note", "value": note})

    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {
                "type": "TextBlock",
                "text": "Approval Request",
                "weight": "Bolder",
                "size": "Large",
                "color": "Accent",
            },
            {"type": "FactSet", "facts": facts},
        ],
        "actions": [
            {
                "type": "Action.OpenUrl",
                "title": "Open & Approve",
                "url": doc_url,
                "style": "positive",
            },
        ],
    }
    return _send_card_to_chat(chat_id, card, docname, doctype)


@frappe.whitelist()
def send_meeting_invite_card(chat_id, doctype, docname, meeting_url, start_time=None, end_time=None):
    """
    Send a rich meeting invite card with a Join button.
    """
    if not all([chat_id, doctype, docname, meeting_url]):
        frappe.throw("chat_id, doctype, docname, and meeting_url are required")

    organiser = frappe.utils.get_fullname(frappe.session.user)
    doc_url = _doc_url(doctype, docname)

    facts = [
        {"title": "Meeting for", "value": f"{doctype}: {docname}"},
        {"title": "Organised by", "value": organiser},
    ]
    if start_time:
        facts.append({"title": "Start", "value": str(start_time)})
    if end_time:
        facts.append({"title": "End", "value": str(end_time)})

    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {
                "type": "TextBlock",
                "text": "Teams Meeting Invitation",
                "weight": "Bolder",
                "size": "Large",
                "color": "Accent",
            },
            {"type": "FactSet", "facts": facts},
        ],
        "actions": [
            {"type": "Action.OpenUrl", "title": "Join Teams Meeting", "url": meeting_url, "style": "positive"},
            {"type": "Action.OpenUrl", "title": "View Document", "url": doc_url},
        ],
    }
    return _send_card_to_chat(chat_id, card, docname, doctype)


@frappe.whitelist()
def send_task_card(chat_id, task_name, assigned_to_email=None, due_date=None, description=None):
    """
    Send a task assignment card. Recipient can click 'View Task' to open it in ERPNext.
    """
    if not chat_id or not task_name:
        frappe.throw("chat_id and task_name are required")

    assigner = frappe.utils.get_fullname(frappe.session.user)
    task_url = _doc_url("Task", task_name)

    facts = [
        {"title": "Task", "value": task_name},
        {"title": "Assigned by", "value": assigner},
    ]
    if assigned_to_email:
        facts.append({"title": "Assigned to", "value": assigned_to_email})
    if due_date:
        facts.append({"title": "Due", "value": str(due_date)})

    body_blocks = [
        {
            "type": "TextBlock",
            "text": "Task Assignment",
            "weight": "Bolder",
            "size": "Large",
            "color": "Accent",
        },
        {"type": "FactSet", "facts": facts},
    ]
    if description:
        body_blocks.append({
            "type": "TextBlock",
            "text": description[:300],
            "wrap": True,
            "color": "Default",
            "size": "Small",
        })

    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": body_blocks,
        "actions": [
            {"type": "Action.OpenUrl", "title": "View Task", "url": task_url, "style": "positive"},
        ],
    }
    return _send_card_to_chat(chat_id, card, task_name, "Task")


@frappe.whitelist()
def send_status_update_card(chat_id, doctype, docname, old_status, new_status, changed_by=None):
    """
    Send a workflow / status change card.
    """
    if not all([chat_id, doctype, docname, new_status]):
        frappe.throw("Required: chat_id, doctype, docname, new_status")

    changer = changed_by or frappe.utils.get_fullname(frappe.session.user)
    doc_url = _doc_url(doctype, docname)

    facts = [
        {"title": "Document", "value": f"{doctype}: {docname}"},
        {"title": "Changed by", "value": changer},
    ]
    if old_status:
        facts.append({"title": "From", "value": old_status})
    facts.append({"title": "To", "value": f"**{new_status}**"})

    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {
                "type": "TextBlock",
                "text": "Status Update",
                "weight": "Bolder",
                "size": "Large",
                "color": "Attention",
            },
            {"type": "FactSet", "facts": facts},
        ],
        "actions": [
            {"type": "Action.OpenUrl", "title": "Open Document", "url": doc_url},
        ],
    }
    return _send_card_to_chat(chat_id, card, docname, doctype)
