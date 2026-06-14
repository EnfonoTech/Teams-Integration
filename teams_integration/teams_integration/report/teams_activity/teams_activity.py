# Copyright (c) 2026, siva@enfono.com
# Feature 11: Teams Activity Report

import frappe


def execute(filters=None):
    filters = filters or {}

    columns = [
        {"label": "Employee / Sender", "fieldname": "sender_display", "fieldtype": "Data", "width": 220},
        {"label": "Sent", "fieldname": "sent_count", "fieldtype": "Int", "width": 80},
        {"label": "Received", "fieldname": "recv_count", "fieldtype": "Int", "width": 90},
        {"label": "Conversations", "fieldname": "conv_count", "fieldtype": "Int", "width": 120},
        {"label": "Last Active", "fieldname": "last_active", "fieldtype": "Datetime", "width": 180},
    ]

    conditions, values = _build_conditions(filters)

    data = frappe.db.sql(
        f"""
        SELECT
            sender_display,
            SUM(CASE WHEN direction = 'Outbound' THEN 1 ELSE 0 END) AS sent_count,
            SUM(CASE WHEN direction = 'Inbound'  THEN 1 ELSE 0 END) AS recv_count,
            COUNT(DISTINCT chat_id)                                  AS conv_count,
            MAX(created_at)                                          AS last_active
        FROM `tabTeams Chat Message`
        WHERE sender_display IS NOT NULL {conditions}
        GROUP BY sender_display
        ORDER BY sent_count DESC
        """,
        values=values,
        as_dict=True,
    )

    return columns, data


def _build_conditions(filters):
    conditions = ""
    values = {}

    if filters.get("from_date"):
        conditions += " AND created_at >= %(from_date)s"
        values["from_date"] = filters["from_date"]

    if filters.get("to_date"):
        conditions += " AND created_at <= %(to_date)s"
        values["to_date"] = str(filters["to_date"]) + " 23:59:59"

    if filters.get("chat_type"):
        if filters["chat_type"] == "Inbound":
            conditions += " AND direction = 'Inbound'"
        elif filters["chat_type"] == "Outbound":
            conditions += " AND direction = 'Outbound'"

    return conditions, values
