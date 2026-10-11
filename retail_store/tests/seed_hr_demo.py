import frappe
from retail_store.tests.check_hr import make_employee, wh, cleanup
def run():
    frappe.set_user("Administrator")
    s=frappe.get_doc("Retail Store Settings"); s.enable_hr=1; s.save()
    cleanup()
    D="@demo.example"
    for first,user,store in (("Dana Downtown","cashier.downtown"+D,None),("Mia Mall","cashier.mall"+D,None),("Marco Manager","manager.downtown"+D,None),("Olivia Owner","owner"+D,None),("Cleo Cleaner",None,wh("Downtown")),("Pat Airport",None,wh("Airport"))):
        make_employee(first,user,store)
    comp=frappe.db.get_value("Salary Component",{"type":"Earning"},"name")
    for emp in frappe.get_all("Employee",filters={"last_name":"RSHR","first_name":["in",["Dana Downtown","Mia Mall"]]},pluck="name"):
        d=frappe.get_doc({"doctype":"Employee Incentive","employee":emp,"salary_component":comp,"incentive_amount":100,"payroll_date":"2026-10-01"})
        d.flags.ignore_validate=True; d.insert(ignore_permissions=True)
    frappe.db.commit()
    print(frappe.get_all("Employee",filters={"last_name":"RSHR"},fields=["name","first_name","custom_store_warehouse","user_id"]))
