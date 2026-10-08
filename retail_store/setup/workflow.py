"""Approval workflow for Material Requests (stock transfer pattern (a)).

Draft --Submit for Approval--> Pending Approval --Approve--> Approved (submitted)
                                               `--Reject--> Rejected --Revise--> Draft
Managers may approve their own drafts directly (Draft --Approve--> Approved).
"""

import frappe

from retail_store.setup.roles import ALL, MANAGERS

WORKFLOW_NAME = "Retail Material Request"

STATES = {
	"Draft": "Info",
	"Pending Approval": "Warning",
	"Approved": "Success",
	"Rejected": "Danger",
}
ACTIONS = ["Submit for Approval", "Approve", "Reject", "Revise"]


def _ensure_masters():
	for state, style in STATES.items():
		if not frappe.db.exists("Workflow State", state):
			frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state, "style": style}).insert(
				ignore_permissions=True
			)
	for action in ACTIONS:
		if not frappe.db.exists("Workflow Action Master", action):
			frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": action}).insert(
				ignore_permissions=True
			)


def setup_material_request_workflow():
	_ensure_masters()
	if frappe.db.exists("Workflow", WORKFLOW_NAME):
		return

	states = []
	for role in ALL:
		states.append({"state": "Draft", "doc_status": "0", "allow_edit": role})
	for role in MANAGERS:
		states.append({"state": "Pending Approval", "doc_status": "0", "allow_edit": role})
		states.append({"state": "Approved", "doc_status": "1", "allow_edit": role})
		states.append({"state": "Rejected", "doc_status": "0", "allow_edit": role})

	transitions = []
	for role in ALL:
		transitions.append(
			{"state": "Draft", "action": "Submit for Approval", "next_state": "Pending Approval", "allowed": role}
		)
		transitions.append({"state": "Rejected", "action": "Revise", "next_state": "Draft", "allowed": role})
	for role in MANAGERS:
		transitions.append({"state": "Pending Approval", "action": "Approve", "next_state": "Approved", "allowed": role})
		transitions.append({"state": "Pending Approval", "action": "Reject", "next_state": "Rejected", "allowed": role})
		transitions.append({"state": "Draft", "action": "Approve", "next_state": "Approved", "allowed": role})

	for t in transitions:
		t["allow_self_approval"] = 1

	enabled = frappe.db.get_single_value("Retail Store Settings", "require_request_approval")
	frappe.get_doc(
		{
			"doctype": "Workflow",
			"workflow_name": WORKFLOW_NAME,
			"document_type": "Material Request",
			"workflow_state_field": "workflow_state",
			"is_active": 1 if enabled is None else int(enabled),
			"send_email_alert": 0,
			"override_status": 0,
			"states": states,
			"transitions": transitions,
		}
	).insert(ignore_permissions=True)


def apply_workflow_toggle(settings):
	if not frappe.db.exists("Workflow", WORKFLOW_NAME):
		return
	active = int(settings.require_request_approval or 0)
	if frappe.db.get_value("Workflow", WORKFLOW_NAME, "is_active") != active:
		wf = frappe.get_doc("Workflow", WORKFLOW_NAME)
		wf.is_active = active
		wf.save(ignore_permissions=True)
