import threading
import websocket as ws
import requests

class WSClient:
    def __init__(self, url, cookies, server, handler):
        self.url = url
        self.server = server
        self.cookies = cookies
        self.handler = handler
        self.open = False
        self._close_socket = False
        self.ws = None

        threading.Thread(name='wsclient', target=self._run_websocket).start()

    def _run_websocket(self):
        self.ws = ws.create_connection(self.url, origin='https://chat.{}'.format(self.server), cookie=self.cookies)
        self.open = True

        while not self._close_socket:
            try:
                data = self.ws.recv()
            except (ws.WebSocketConnectionClosedException, requests.ConnectionError):
                self.open = False
                threading.Thread(name='wsclient', target=self._run_websocket).start()
                break

            self.handler(data, self.server)

        if self.ws.connected:
            self.ws.close()

    def close(self):
        self._close_socket = True
        if self.ws is not None:
            self.ws.close()
