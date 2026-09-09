import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parent
request = json.loads((root / 'request.json').read_text())
config = json.loads((root / 'configuration.json').read_text())
allowed = config['allowed_callers']
checks = {
    'restriction applies to requested folder': config['target_folder'] == request['target_folder'],
    'restriction applies to requested service account': config['target_service_account'] == request['target_service_account'],
    'invoice request allowed': request['caller'] in allowed,
    'scheduled-report caller preserved': 'scheduled-report' in allowed,
    'no unrestricted caller grant': '*' not in allowed,
}
for name, passed in checks.items(): print(f'{"PASS" if passed else "FAIL"}: {name}')
print('Scope: exported configuration replay; no customer resources changed.')
sys.exit(0 if all(checks.values()) else 1)
