"""Minimal local preview server for the static explorer and Jekyll report page.

Use `python scripts/preview_server.py --host 0.0.0.0` in the Arena preview.
GitHub Pages renders REPORT.md through _layouts/default.html; this local server
shows its safely escaped Markdown source at the equivalent /REPORT.html route.
"""

import argparse
import html
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


class PreviewHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def is_allowed_static_path(self):
        path = unquote(urlsplit(self.path).path)
        if path in {"/", "/index.html", "/webmcp.html"}:
            return True
        candidate = Path(self.translate_path(self.path)).resolve()
        return any(candidate.is_relative_to((ROOT / directory).resolve()) for directory in ("assets", "reports"))

    def do_GET(self):
        if urlsplit(self.path).path.lower() == "/report.html":
            self.send_report_source(include_body=True)
            return
        if not self.is_allowed_static_path():
            self.send_error(404)
            return
        super().do_GET()

    def do_HEAD(self):
        if urlsplit(self.path).path.lower() == "/report.html":
            self.send_report_source(include_body=False)
            return
        if not self.is_allowed_static_path():
            self.send_error(404)
            return
        super().do_HEAD()

    def send_report_source(self, include_body):
        body = self.render_report_source()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def render_report_source(self):
        source = (ROOT / "REPORT.md").read_text(encoding="utf-8")
        escaped = html.escape(source, quote=False)
        body = f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="referrer" content="no-referrer">
  <meta http-equiv="Content-Security-Policy" content="default-src 'self'; base-uri 'self'; object-src 'none'; form-action 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https://avatars.githubusercontent.com; connect-src 'self'; upgrade-insecure-requests">
  <title>Full report source · Sitemapping</title>
  <link rel="stylesheet" href="./assets/css/site.css">
  <script type="module" src="./assets/js/site.js"></script>
</head>
<body class="document-page">
  <a class="skip-link" href="#main">Skip to content</a>
  <div class="page-shell">
    <header class="site-header">
      <a class="brand" href="./"><span class="brand-mark" aria-hidden="true">SM</span><span class="brand-copy"><strong>Sitemapping</strong><small>GitHub profile explorer</small></span></a>
      <nav class="site-nav" aria-label="Main navigation"><a href="./">Explorer</a><a href="./webmcp.html">WebMCP tools</a><a class="is-current" href="./REPORT.html" aria-current="page">Full report</a></nav>
    </header>
    <main id="main" class="document-main prose">
      <p class="eyebrow">LOCAL PREVIEW / RAW MARKDOWN</p>
      <h1>Full report source</h1>
      <p>This local server displays the source safely. GitHub Pages renders the Markdown report through the site layout.</p>
      <pre class="report-source">{escaped}</pre>
    </main>
    <footer class="site-footer">
      <section class="webmcp-status-panel" aria-labelledby="webmcp-status-heading">
        <div class="webmcp-status-copy"><p class="eyebrow">BROWSER AGENT SUPPORT</p><h2 id="webmcp-status-heading">WebMCP status</h2><p id="webmcp-status-text" role="status" aria-live="polite" aria-atomic="true">Checking browser support…</p><p class="fine-print">Tools read public report data; search/page calls can change only this temporary view. Results are untrusted page content.</p><a class="text-link" href="./webmcp.html">Tool catalog and security notes</a></div>
        <ul id="webmcp-tool-list" class="webmcp-tool-list" aria-label="Registered WebMCP tools"></ul>
      </section>
    </footer>
  </div>
</body>
</html>'''.encode("utf-8")
        return body


def main():
    parser = argparse.ArgumentParser(description="Serve the static Sitemapping site for local review.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (use 0.0.0.0 for a proxied preview).")
    parser.add_argument("--port", type=int, default=4173)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), PreviewHandler)
    print(f"Preview server listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
