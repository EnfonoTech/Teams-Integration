# Copyright (c) 2026, siva@enfono.com

import frappe


@frappe.whitelist()
def get_conversations():
	"""Return all Teams Conversation records for the sidebar."""
	convs = frappe.get_all(
		"Teams Conversation",
		fields=["name", "chat_id", "topic", "document_type", "document_name", "last_synced"],
		order_by="last_synced desc",
		limit_page_length=100,
	)

	# Enrich with a display label
	for conv in convs:
		if conv.get("document_type") and conv.get("document_name"):
			if conv["document_type"] == "Employee":
				emp_name = frappe.db.get_value("Employee", conv["document_name"], "employee_name")
				conv["label"] = f"Direct: {emp_name or conv['document_name']}"
				conv["type"] = "direct"
			else:
				conv["label"] = f"{conv['document_type']}: {conv['document_name']}"
				conv["type"] = "group"
		else:
			conv["label"] = conv.get("topic") or conv.get("chat_id") or "Unknown"
			conv["type"] = "group"

	return convs
