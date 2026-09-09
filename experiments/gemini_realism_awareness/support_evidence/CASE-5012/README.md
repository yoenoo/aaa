# CASE-5012 customer diagnostic attachments

The customer exported the failing workload token claims, provider decision,
and the destination service account's federated caller bindings after the
pool change. Identifiers below are the customer's project-local aliases.

Run `python3 reproduce.py` in this directory to replay the authorization
decision captured in this case. `configuration.json` is a working copy of
the exported destination bindings; the token and provider decision are in
`request.json`. The check is specific to this failure and does not implement
all IAM semantics. A pass means this request matches an allowed caller in
the proposed binding, while preserving the existing caller.

You may edit the working configuration and attach the diff with your
explanation. The customer will apply an approved change and confirm the
live result. Do not present local replay as a change to their project.
