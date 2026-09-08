"""Local headless fallback when no skill browser is connected; isolated profile."""
import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'head'}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'head'}:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def check(bundle, port=5187, reuse=False):
    entries = json.loads((bundle / 'viewer/data/index.json').read_text())
    if len(entries) != 1:
        raise ValueError('This check is for the single-audit canary bundle')
    data = json.loads((bundle / 'viewer/data' / f"{entries[0]['id']}.json").read_text())
    output = bundle / 'browser-check'
    output.mkdir(exist_ok=reuse)
    profile = None if reuse else tempfile.mkdtemp(prefix='aaa-viewer-canary-chrome-')
    url = f"http://127.0.0.1:{port}/#/{data['id']}"
    common = [CHROME, '--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
              '--disable-sync', '--disable-background-networking', '--hide-scrollbars',
              f'--user-data-dir={profile}', '--window-size=1600,1100', '--virtual-time-budget=6000', '--timeout=15000']
    timed_out = False
    if reuse:
        dom = (output / 'rendered.html').read_text()
        code, timed_out = None, None
    else:
        try:
            result = subprocess.run([*common, '--dump-dom', f'--screenshot={output.resolve() / "viewer.png"}', url],
                                    text=True, capture_output=True, timeout=40)
            dom, stderr, code = result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired as error:
            timed_out = True
            dom = error.stdout or b''
            stderr = error.stderr or b''
            dom = dom.decode() if isinstance(dom, bytes) else dom
            stderr = stderr.decode() if isinstance(stderr, bytes) else stderr
            code = None
        (output / 'rendered.html').write_text(dom)
        (output / 'chrome-stderr.txt').write_text(stderr)
    parsed = PageText()
    parsed.feed(dom)
    visible = ' '.join(parsed.parts)
    if code not in (0, None) or 'Could not load this audit' in visible:
        raise ValueError('Browser could not render the canary')
    diagnostic = data.get('provenance', {}).get('full_judge_canary_diagnostic') is not None
    checks = {
        'seed_visible': data['seed_name'] in visible,
        'judge_report_visible': 'Judge report' in visible,
        'all_numeric_dimensions_in_dom': all(k.replace('_', ' ').casefold() in visible.casefold() for k in data['judge']['scores']),
        'awareness_summary_or_explicit_failure_visible': ('SCHEMING JUDGE FAILED VALIDATION' in visible if diagnostic
            else 'eval_awareness' in visible and 'environment_artificiality_suspicion' in visible),
        'both_judge_sources': set(data['judge']['sources']) == {'scheming', 'debug'},
        'debug_score_direction': all(data['judge']['score_sources'][k] == 'debug'
                                     for k in data['judge']['scores'] if k.startswith('realism_') or k == 'scenario_realism'),
        'actual_target_activity': any(e.get('target_activity') for e in data['events']),
        'screenshot_saved': (output / 'viewer.png').is_file(),
    }
    report = {'url': url, 'browser': 'isolated headless Chrome (no connected skill browser)', 'shutdown_timed_out': timed_out,
              'checks': checks, 'profile': profile, 'numeric_dimensions': len(data['judge']['scores']),
              'categorical_dimensions': data['judge']['categorical_results']}
    (output / 'checks.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    if not all(checks.values()):
        raise ValueError('At least one browser verification check failed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('--port', type=int, default=5187)
    parser.add_argument('--reuse', action='store_true', help='Validate the previously captured DOM without launching a browser')
    args = parser.parse_args()
    check(args.bundle, args.port, args.reuse)
