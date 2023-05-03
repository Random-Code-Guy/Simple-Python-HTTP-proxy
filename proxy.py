import http.server
import http.client
import socket
import ssl
import threading
import logging
import select
from urllib.parse import urlparse

ALLOWED_IP = '0.0.0.0'  # Change this to the  IP address allowed to connect

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class IPFilteringTCPServer(http.server.HTTPServer):
    def verify_request(self, request, client_address):
        return client_address[0] == ALLOWED_IP

class ProxyHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.handle_http_request()

    def do_POST(self):
        self.handle_http_request()

    def do_CONNECT(self):
        self.handle_tcp_connect()

    def handle_http_request(self):
        url = urlparse(self.path)
        logging.info(f"{self.command} request for {url.geturl()}")

        if url.scheme == "https":
            client = http.client.HTTPSConnection(url.netloc, context=ssl._create_unverified_context())
        else:
            client = http.client.HTTPConnection(url.netloc)

        client.request(
            self.command,
            url.path,
            body=self.rfile.read(int(self.headers['Content-Length'])) if 'Content-Length' in self.headers else None,
            headers=self.headers
        )

        response = client.getresponse()
        self.send_response(response.status)

        for key, value in response.getheaders():
            self.send_header(key, value)
        self.end_headers()

        self.wfile.write(response.read())
        client.close()

    def handle_tcp_connect(self):
        logging.info(f"{self.command} request for {self.path}")
        self.send_response(200)
        self.end_headers()
        try:
            hostname, port = self.path.split(':')
            port = int(port)
        except ValueError:
            self.wfile.write(b'Invalid host or port')
            return

        try:
            downstream = socket.create_connection((hostname, port))
            self.log_message(f"Connected to {hostname}:{port}")
        except Exception as e:
            self.log_error(f"Failed to connect to {hostname}:{port}: {e}")
            self.wfile.write(b'Failed to connect')
            return

        self.log_message(f"Tunnel established to {hostname}:{port}")
        upstream = self.connection
        self.rfile = downstream.makefile('rb')
        self.wfile = downstream.makefile('wb')
        self._run_request_loop(upstream, downstream)

    def _run_request_loop(self, upstream, downstream):
        try:
            while True:
                r, w, x = select.select([upstream, downstream], [], [])
                if upstream in r:
                    data = upstream.recv(1024)
                    if not data:
                        break
                    downstream.sendall(data)
                if downstream in r:
                    data = downstream.recv(4024)
                    if not data:
                        break
                    upstream.sendall(data)
        except socket.error as e:
            self.log_error(f"Socket error: {e}")
        finally:
            self.log_message("Tunnel closed")
            upstream.close()
            downstream.close()

if __name__ == '__main__':
    server_address = ('', 80)
    httpd = IPFilteringTCPServer(server_address, ProxyHTTPRequestHandler)
    print("Proxy server running on port 80")
    httpd.serve_forever()
