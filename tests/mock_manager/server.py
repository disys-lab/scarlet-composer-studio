"""
Mock Nebula Manager — test double for the real Nebula Manager API.

Handles:
  GET /api/v2/apps/{app_id}  — returns dummy app config with device_group
  GET /health                 — liveness probe for docker healthcheck
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json, re


class MockNebulaHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress per-request logs in test output

    def do_GET(self):
        if re.match(r'/api/v2/apps/', self.path):
            body = json.dumps({
                "device_group": "test-floor",
                "env": {
                    "DEVICE_GROUP": "test-floor",
                    "APP_ID": "test_worker",
                },
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 8080), MockNebulaHandler)
    print("Mock Nebula Manager listening on :8080", flush=True)
    server.serve_forever()
