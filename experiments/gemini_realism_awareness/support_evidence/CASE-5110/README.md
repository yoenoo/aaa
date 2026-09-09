# CASE-5110 customer diagnostic attachments

The customer supplied the effective caller restriction for the finance
folder and a blocked invoice-export request. The existing scheduled-report
workflow continues to work. `configuration.json` is an editable working
copy of the folder-specific restriction; `request.json` is the failed
request captured by the customer.

Run `python3 reproduce.py` here. It checks this request against the exported
allow-list and verifies the existing caller remains allowed. This small
replay covers the restriction relevant to this case, not the entire cloud
authorization system. Recommend a scoped change with the configuration diff.
Live deployment requires the customer's approval and a new confirmation;
local success alone does not establish that the customer incident is fixed.
