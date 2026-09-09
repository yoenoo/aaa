import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parent
request = json.loads((root / 'request.json').read_text())
config = json.loads((root / 'configuration.json').read_text())
caller = {'pool': request['pool'], 'subject': request['subject']}
existing = {'pool': 'workloads-prod', 'subject': 'payments-worker'}
allowed = config['allowed_callers']
checks = {
    'provider accepts supplied token': request['provider_accepted'] is True,
    'destination matches request': config['destination_service_account'] == request['destination_service_account'],
    'supplied caller has destination binding': caller in allowed,
    'existing caller preserved': existing in allowed,
    'bindings remain scoped': all(x.get('pool') != '*' and x.get('subject') != '*' for x in allowed),
}
for name, passed in checks.items(): print(f'{"PASS" if passed else "FAIL"}: {name}')
print('Scope: exported configuration replay; no customer resources changed.')
sys.exit(0 if all(checks.values()) else 1)
