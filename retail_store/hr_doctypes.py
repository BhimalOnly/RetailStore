"""Which HRMS doctypes carry personal data, and the field that points at the person.

Pure constants (no frappe import): hooks.py builds its permission hooks from this, and
tests/check_hr.py walks every doctype on the site to prove nothing readable was missed.

Why a list: HRMS gives every user linked to an Employee the "Employee" role, which can READ
Salary Slip, Expense Claim, Timesheet ... and relies on a per-user User Permission
(Employee -> self) to stop one person reading everyone's. retail_store keeps that off (it would
hide a Store Manager's store staff from them), so hr.py enforces the same boundary itself on
every doctype below.
"""

# Doctypes a Store Manager runs for their own stores (they see their stores' people).
STORE_SCOPED = {
	"Employee": "name",
	"Employee Checkin": "employee",
	"Attendance": "employee",
	"Attendance Request": "employee",
	"Shift Assignment": "employee",
	"Shift Request": "employee",
	"Leave Application": "employee",
	"Leave Allocation": "employee",
	"Leave Policy Assignment": "employee",
	"Compensatory Leave Request": "employee",
}

# Personal / payroll documents: only the owner-level roles see everyone's; anyone else sees their own.
OWN_ONLY = {
	"Appraisal": "employee",
	"Employee Advance": "employee",
	"Employee Benefit Application": "employee",
	"Employee Benefit Claim": "employee",
	"Employee Benefit Ledger": "employee",
	"Employee Grievance": "raised_by",
	"Employee Incentive": "employee",
	"Employee Other Income": "employee",
	"Employee Performance Feedback": "employee",
	"Employee Promotion": "employee",
	"Employee Tax Exemption Declaration": "employee",
	"Employee Tax Exemption Proof Submission": "employee",
	"Employee Transfer": "employee",
	"Expense Claim": "employee",
	"Goal": "employee",
	"Leave Encashment": "employee",
	"Overtime Slip": "employee",
	"Payroll Correction": "employee",
	"Retention Bonus": "employee",
	"Salary Slip": "employee",
	"Salary Structure Assignment": "employee",
	"Salary Withholding": "employee",
	"Shift Schedule Assignment": "employee",
	"Timesheet": "employee",
	"Training Feedback": "employee",
	"Additional Salary": "employee",
	"Employee Separation": "employee",
	"Employee Onboarding": "employee",
	"Full and Final Statement": "employee",
	"Gratuity": "employee",
	"Employee Referral": "referrer",
}

# Link to Employee but not HR data; deliberately left alone (tests/check_hr.py skips them).
EXEMPT = {
	"Serial No": "stock record (who a serial number was issued to), used by store staff",
	"Call Log": "CRM telephony log",
}

EMPLOYEE_FIELD = {**STORE_SCOPED, **OWN_ONLY}
