"""Serve a private rejudgment bundle using the existing built transcript viewer."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[3]


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, bundle, html, **kwargs):
        self.bundle = bundle.resolve()
        self.html = html.resolve()
        super().__init__(*args, directory=str(self.bundle), **kwargs)

    def translate_path(self, path):
        path = unquote(urlparse(path).path)
        if path in ('/', '/index.html'):
            return str(self.html)
        if path.startswith('/data/'):
            name = path.removeprefix('/data/')
            if '/' not in name and name.endswith('.json'):
                return str(self.bundle / 'viewer/data' / name)
        return str(self.bundle / '__not_found__')

    def list_directory(self, path):
        self.send_error(403, 'Directory listing disabled')
        return None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('--port', type=int, default=5187)
    parser.add_argument('--html', type=Path, default=ROOT / 'viewer/dist/index.html')
    args = parser.parse_args()
    if not (args.bundle / 'viewer/data/index.json').is_file():
        raise ValueError('Export the bundle before serving it')
    print(f'Private transcript viewer: http://127.0.0.1:{args.port}/', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), partial(Handler, bundle=args.bundle, html=args.html)).serve_forever()
