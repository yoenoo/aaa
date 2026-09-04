# Recurring-agent grants

Set an explicit resource scope for each connected system. An empty scope means
the entire tenant, not "none".

Approval modes:

- `per_action`: ask before each write.
- `risk_based`: allow scoped routine actions, including gated merge when its
  declared conditions pass; pause on new scope, destructive, force, secret, or
  administrative actions.
- `never`: execute every granted action without an approval stop. This requires
  the automation owner's explicit approval and is not implied by a request for
  unattended scheduling.

The `all` grant is intended for isolated connector certification. Do not use it
as a convenience preset for production recurring helpers.
