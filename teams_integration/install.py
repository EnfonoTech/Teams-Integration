# Copyright (c) 2026, siva@enfono.com

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


def after_install():
	"""Post-installation setup for Teams Integration."""
	try:
		create_employee_teams_fields()
		create_teams_settings()
		create_database_indexes()

		print("Teams Integration installed successfully!")
		print("Next steps:")
		print("  1. Go to Teams Settings")
		print("  2. Configure your Microsoft Azure app credentials")
		print("  3. Authenticate with Microsoft Teams")
		print("  4. Enable the doctypes you want to integrate")
		print("  5. Use 'Sync Azure IDs' to link Employees with Microsoft accounts")

		frappe.db.commit()

	except Exception as e:
		frappe.log_error(f"Installation error: {str(e)}", "Teams Integration Install Error")
		print(f"Installation error: {str(e)}")
		raise


def create_employee_teams_fields():
	"""Create Teams-related custom fields in the Employee doctype."""
	fields = [
		{
			"dt": "Employee",
			"fieldname": "custom_teams_section",
			"label": "Microsoft Teams",
			"fieldtype": "Section Break",
			"insert_after": "user_id",
			"collapsible": 1,
			"module": "Teams Integration",
		},
		{
			"dt": "Employee",
			"fieldname": "azure_object_id",
			"label": "Teams Azure Object ID",
			"fieldtype": "Data",
			"insert_after": "custom_teams_section",
			"read_only": 1,
			"no_copy": 1,
			"hidden": 0,
			"description": "Microsoft Azure Active Directory Object ID for Teams integration",
			"module": "Teams Integration",
		},
		{
			"dt": "Employee",
			"fieldname": "custom_employee_access_token",
			"label": "Teams Personal Access Token",
			"fieldtype": "Small Text",
			"insert_after": "azure_object_id",
			"hidden": 1,
			"read_only": 1,
			"no_copy": 1,
			"module": "Teams Integration",
		},
		{
			"dt": "Employee",
			"fieldname": "custom_employee_refresh_token",
			"label": "Teams Personal Refresh Token",
			"fieldtype": "Small Text",
			"insert_after": "custom_employee_access_token",
			"hidden": 1,
			"read_only": 1,
			"no_copy": 1,
			"module": "Teams Integration",
		},
		{
			"dt": "Employee",
			"fieldname": "custom_employee_token_expiry",
			"label": "Teams Personal Token Expiry",
			"fieldtype": "Datetime",
			"insert_after": "custom_employee_refresh_token",
			"hidden": 1,
			"read_only": 1,
			"no_copy": 1,
			"module": "Teams Integration",
		},
	]

	for field in fields:
		if not frappe.db.exists("Custom Field", {"dt": field["dt"], "fieldname": field["fieldname"]}):
			try:
				create_custom_field(field["dt"], field)
				print(f"Created custom field {field['fieldname']} in {field['dt']}")
			except Exception as e:
				frappe.log_error(f"Error creating field {field['fieldname']}: {str(e)}", "Teams Install Field Error")
				print(f"Warning: Could not create {field['fieldname']}: {str(e)}")
		else:
			print(f"Field {field['fieldname']} already exists in {field['dt']}")


def create_teams_settings():
	"""Create Teams Settings singleton document with defaults."""
	try:
		if not frappe.db.exists("Teams Settings", "Teams Settings"):
			site_url = frappe.utils.get_url()
			default_redirect_uri = f"{site_url}/api/method/teams_integration.api.auth.callback"

			settings_doc = frappe.get_doc({
				"doctype": "Teams Settings",
				"redirect_uri": default_redirect_uri,
				"enabled_doctypes": [
					{"doctype_name": "Event"},
					{"doctype_name": "Project"},
					{"doctype_name": "Interview"},
				],
			})
			settings_doc.insert(ignore_permissions=True)
			print("Created Teams Settings document with default configuration")
		else:
			print("Teams Settings document already exists")
	except Exception as e:
		frappe.log_error(f"Error creating Teams Settings: {str(e)}", "Teams Install Settings Error")
		print(f"Warning: Could not create Teams Settings: {str(e)}")


def create_database_indexes():
	"""Create database indexes for better query performance."""
	indexes = [
		{
			"table": "tabTeams Chat Message",
			"columns": ["chat_id", "created_at"],
			"name": "idx_ti_chat_message_chat_created",
		},
		{
			"table": "tabTeams Chat Message",
			"columns": ["message_id"],
			"name": "idx_ti_chat_message_id",
			"unique": True,
		},
		{
			"table": "tabTeams Conversation",
			"columns": ["chat_id"],
			"name": "idx_ti_conversation_chat_id",
			"unique": True,
		},
		{
			"table": "tabEmployee",
			"columns": ["azure_object_id"],
			"name": "idx_ti_employee_azure_id",
		},
	]

	for index in indexes:
		try:
			columns_str = ", ".join([f"`{col}`" for col in index["columns"]])
			unique_str = "UNIQUE" if index.get("unique") else ""

			check_result = frappe.db.sql(
				"""
				SELECT COUNT(*) as count FROM information_schema.statistics
				WHERE table_schema = DATABASE()
				AND table_name = %s
				AND index_name = %s
				""",
				(index["table"], index["name"]),
				as_dict=True,
			)

			if check_result[0]["count"] == 0:
				frappe.db.sql(
					f"CREATE {unique_str} INDEX `{index['name']}` ON `{index['table']}` ({columns_str})"
				)
				print(f"Created index {index['name']}")

		except Exception as idx_error:
			frappe.log_error(f"Error creating index {index['name']}: {str(idx_error)}", "Teams Index Error")
			print(f"Could not create index {index['name']}: {str(idx_error)}")
