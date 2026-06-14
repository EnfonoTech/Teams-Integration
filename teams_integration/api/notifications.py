# Copyright (c) 2026, siva@enfono.com
# Feature 4: Workflow State → Teams Notification

import frappe


# ---------------------------------------------------------------------------
# Frappe doc_events hooks
# ---------------------------------------------------------------------------

def before_doc_save(doc, method=None):
    """
    Store the current workflow_state from the database before this save,
    so on_doc_update can detect whether it changed.
    """
    if not getattr(doc, "workflow_state", None):
        return
    if frappe.db.exists(doc.doctype, doc.name):
        try:
            doc._prev_workflow_state = frappe.db.get_value(
                doc.doctype, doc.name, "workflow_state"
            )
        except Exception:
            pass


def on_doc_update(doc, method=None):
    """
    After save: if the workflow_state changed and a Teams chat is linked,
    send a plain-text notification and an adaptive card.
    """
    chat_id = getattr(doc, "custom_teams_chat_id", None)
    if not chat_id:
        return

    new_state = getattr(doc, "workflow_state", None)
    if not new_state:
        return

    prev_state = getattr(doc, "_prev_workflow_state", None)
    if prev_state == new_state:
        return

    try:
        changer = frappe.utils.get_fullname(frappe.session.user)

        # Plain-text fallback message
        change_desc = (
            f"from **{prev_state}** → **{new_state}**" if prev_state else f"set to **{new_state}**"
        )
        plain_message = (
            f"📋 *{doc.doctype}* [{doc.name}] status changed {change_desc} by {changer}"
        )

        from .chat import send_message_to_chat
        send_message_to_chat(chat_id, plain_message, doc.name, doc.doctype)

        # Also send an adaptive card for richer display
        try:
            from .adaptive_cards import send_status_update_card
            send_status_update_card(
                chat_id=chat_id,
                doctype=doc.doctype,
                docname=doc.name,
                old_status=prev_state,
                new_status=new_state,
                changed_by=changer,
            )
        except Exception:
            pass  # Card is bonus; don't fail the whole hook if it errors

    except Exception as e:
        frappe.log_error(
            f"Workflow notification failed for {doc.doctype} {doc.name}: {str(e)}",
            "Teams Workflow Notification Error",
        )
