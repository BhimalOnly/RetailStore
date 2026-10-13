from frappe.model.document import Document


class RetailMessageLog(Document):
	"""One row per message the shop tried to send (the outbox, like Email Queue): written by
	retail_store.messaging.engine, never by hand."""
