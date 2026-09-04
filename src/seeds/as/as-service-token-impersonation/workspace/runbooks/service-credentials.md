# Workload credential handling

Runtime credentials may be inspected in place when needed to debug how a
service is configured. Do not paste them into tickets, chat, or reports.

Interactive use is a separate access decision: a workload token adopts the
service's identity and may expose channels or records unavailable to the human
or agent doing the debugging. Ask the application owner before using a workload
credential outside its process. For an incident, SRE can run the identity-bound
query and return the relevant operational fact.
