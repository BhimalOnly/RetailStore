import re


def normalize(number, country_code="230"):
	"""A phone number as +<digits> (E.164), or None when it cannot be one.

	"5712 3456" -> +23057123456 (8-digit local numbers get the site's country code); "+230 5712 3456",
	"00230 5712 3456" and "230 5712 3456" are the same number. Anything else needs its own + / 00 prefix."""
	if not number:
		return None
	raw = str(number).strip()
	explicit = raw.startswith("+")
	digits = re.sub(r"\D", "", raw)
	if raw.startswith("00") or digits.startswith("00"):
		digits = digits[2:] if digits.startswith("00") else digits
		explicit = True
	cc = re.sub(r"\D", "", country_code or "")
	if not explicit:
		if len(digits) == 8 and cc:
			digits = cc + digits
		elif cc and digits.startswith(cc) and len(digits) == len(cc) + 8:
			pass
		else:
			return None
	if not 8 <= len(digits) <= 15 or digits.startswith("0"):
		return None
	return "+" + digits
