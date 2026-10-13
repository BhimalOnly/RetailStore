"""Senders. Each takes a prepared message and either returns the provider's reference or raises
ProviderError(transient=...): transient (timeout, 5xx, 429) is retried later, anything else (bad token,
unknown template, rejected number) fails at once because trying again cannot help."""

import re

import frappe
import requests

TIMEOUT = 15


class ProviderError(Exception):
	def __init__(self, message, transient=False):
		super().__init__(message)
		self.transient = transient


def _post_or_get(method, url, **kwargs):
	try:
		return requests.request(method, url, timeout=TIMEOUT, **kwargs)
	except (requests.Timeout, requests.ConnectionError) as e:
		raise ProviderError(f"Could not reach the provider ({type(e).__name__})", transient=True) from e
	except requests.RequestException as e:
		raise ProviderError(f"Request failed ({type(e).__name__})") from e


def _transient(status):
	return status >= 500 or status == 429


class DryRun:
	"""Sends nothing: the message is only logged. The default, so a new site never messages anyone by accident."""

	name = "Dry run"

	def __init__(self, settings):
		pass

	def send(self, to, body, template=None, language=None, variables=None):
		return "dry-run-" + frappe.generate_hash(length=8)


class MetaWhatsApp:
	name = "Meta WhatsApp Cloud API"

	def __init__(self, settings):
		self.phone_id = (settings.get("whatsapp_phone_number_id") or "").strip()
		self.token = settings.get_password("whatsapp_access_token", raise_exception=False) or ""
		self.version = (settings.get("whatsapp_api_version") or "v21.0").strip()
		self.base = (settings.get("whatsapp_api_base") or "https://graph.facebook.com").strip().rstrip("/")

	def send(self, to, body, template=None, language=None, variables=None):
		if not self.phone_id or not self.token:
			raise ProviderError("WhatsApp is not set up: add the phone number ID and access token in Retail Store Settings > Messages.")
		if not _allowed_url(self.base):
			raise ProviderError("The WhatsApp API address must start with https://")
		number = to.lstrip("+")
		if template:
			payload = {
				"messaging_product": "whatsapp",
				"to": number,
				"type": "template",
				"template": {
					"name": template,
					"language": {"code": language or "en"},
					"components": [
						{"type": "body", "parameters": [{"type": "text", "text": str(v)} for v in (variables or [])]}
					]
					if variables
					else [],
				},
			}
		else:
			payload = {"messaging_product": "whatsapp", "to": number, "type": "text", "text": {"body": body}}
		r = _post_or_get(
			"POST", f"{self.base}/{self.version}/{self.phone_id}/messages", json=payload, headers={"Authorization": f"Bearer {self.token}"}
		)
		if r.status_code == 200:
			try:
				return r.json()["messages"][0]["id"]
			except (ValueError, KeyError, IndexError):
				return ""
		try:
			detail = r.json()["error"]["message"]
		except (ValueError, KeyError, TypeError):
			detail = r.text[:200]
		raise ProviderError(f"WhatsApp refused the message (HTTP {r.status_code}): {detail}", transient=_transient(r.status_code))


class GenericHttpSms:
	name = "Generic HTTP gateway"

	def __init__(self, settings):
		self.url = (settings.get("sms_gateway_url") or "").strip()
		self.method = (settings.get("sms_http_method") or "POST").upper()
		self.params = settings.get("sms_params") or ""
		self.username = settings.get("sms_username") or ""
		self.password = settings.get_password("sms_password", raise_exception=False) or ""
		self.sender = settings.get("sms_sender_id") or ""
		self.success_text = (settings.get("sms_success_text") or "").strip()

	def send(self, to, body, template=None, language=None, variables=None):
		if not self.url:
			raise ProviderError("The SMS gateway is not set up: add its address in Retail Store Settings > Messages.")
		if not _allowed_url(self.url):
			raise ProviderError("The SMS gateway address must start with https://")
		values = {
			"to": to,
			"to_digits": to.lstrip("+"),
			"message": body,
			"sender": self.sender,
			"username": self.username,
			"password": self.password,
		}
		params = {}
		for line in self.params.splitlines():
			if "=" not in line:
				continue
			key, _, val = line.partition("=")
			params[key.strip()] = re.sub(r"\{(\w+)\}", lambda m: str(values.get(m.group(1), m.group(0))), val.strip())
		if self.method == "GET":
			r = _post_or_get("GET", self.url, params=params)
		else:
			r = _post_or_get("POST", self.url, data=params)
		if not 200 <= r.status_code < 300:
			raise ProviderError(f"The SMS gateway refused the message (HTTP {r.status_code}): {r.text[:200]}", transient=_transient(r.status_code))
		if self.success_text and self.success_text not in r.text:
			raise ProviderError(f"The SMS gateway did not confirm the message: {r.text[:200]}")
		return r.text.strip()[:60]


def _allowed_url(url):
	"""https only; plain http is for a gateway on this same machine (development)."""
	return url.startswith("https://") or url.startswith("http://127.0.0.1") or url.startswith("http://localhost")


PROVIDERS = {
	("WhatsApp", "Dry run"): DryRun,
	("WhatsApp", "Meta WhatsApp Cloud API"): MetaWhatsApp,
	("SMS", "Dry run"): DryRun,
	("SMS", "Generic HTTP gateway"): GenericHttpSms,
}


def get_provider(channel, settings):
	field = "whatsapp_provider" if channel == "WhatsApp" else "sms_provider"
	chosen = settings.get(field) or "Dry run"
	return PROVIDERS.get((channel, chosen), DryRun)(settings)


def secrets(settings):
	"""Values that must never appear in a log row."""
	vals = [settings.get_password(f, raise_exception=False) for f in ("whatsapp_access_token", "sms_password")]
	return [v for v in vals if v]
