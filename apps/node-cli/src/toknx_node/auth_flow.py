import queue
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Dict, Optional
from urllib.parse import parse_qs, urlencode, urlparse


class CallbackHandler(BaseHTTPRequestHandler):
    result_queue: Optional[queue.Queue[Dict]] = None

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        params = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        if self.result_queue is not None:
            self.result_queue.put(params)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ToknX login complete. You can close this window.")

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def login_via_browser(api_base_url: str, *, state: str, username: str) -> dict:
    callback_host = "127.0.0.1"
    callback_port = 8787
    callback_url = f"http://{callback_host}:{callback_port}/callback"
    result_queue: queue.Queue[dict] = queue.Queue()
    CallbackHandler.result_queue = result_queue
    server = HTTPServer((callback_host, callback_port), CallbackHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    params = urlencode(
        {
            "redirect_uri": callback_url,
            "state": state,
            "username": username,
        }
    )
    webbrowser.open(f"{api_base_url}/auth/github?{params}")
    result = result_queue.get(timeout=120)
    server.shutdown()
    return result
