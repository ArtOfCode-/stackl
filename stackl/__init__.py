import sys
import threading
from logging import StreamHandler
import logging
import os.path
import pickle
import json
import requests
from bs4 import BeautifulSoup
from stackl.errors import LoginError, InvalidOperationError
from stackl.models import Room
from stackl.events import Event
from stackl.wsclient import WSClient


VERSION = '0.0.1'


class ChatClient:
    def __init__(self, **kwargs):
        """
        Initialise a new ChatClient object. Valid kwargs are:
        :param kwargs['default_server']: one of stackexchange.com, stackoverflow.com, or meta.stackexchange.com,
                                         depending on where you want the client to default to.
        :param kwargs['log_location']: a logging.Handler object (e.g. StreamHandler or FileHandler) specifying a log
                                       location
        :param kwargs['log_level']: an integer, usually one of the logging.* constants such as logging.DEBUG, specifying
                                    the minimum effective log level
        """
        self.default_server = kwargs.get('default_server') or 'stackexchange.com'
        log_location = kwargs.get('log_location') or StreamHandler(stream=sys.stdout)
        log_level = kwargs.get('log_level') or logging.DEBUG
        self.logger = logging.getLogger('stackl')
        self.logger.setLevel(log_level)
        self.logger.addHandler(log_location)
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'stackl'})
        self.rooms = []

        self._handlers = []
        self._sockets = {}
        self._fkeys = {}
        self._authed_servers = []

    def login(self, email, password, **kwargs):
        """
        Log the client instance into Stack Exchange. Will default to logging in using cached cookies, if provided, and
        fall back to logging in with credentials.
        :param email: the email of the Stack Exchange account you want to log in as
        :param password: the corresponding account password
        :param kwargs: pass "cookie_file" to specify where cached cookies are located (must be a pickle file)
        :return: the logged-in requests.Session if successful
        """
        logged_in = False
        if 'cookie_file' in kwargs and os.path.exists(kwargs['cookie_file']):
            with open(kwargs['cookie_file'], 'rb') as f:
                self.session.cookies.update(pickle.load(f))
                logged_in = self._verify_login(kwargs.get('servers') or [self.default_server])
                if logged_in is False:
                    self.logger.warn('Cookie login failed. Falling back to credential login.')
                    for n, v in self.session.cookies.items():
                        self.logger.info('{}: {}'.format(n, v))

        if not logged_in:
            logged_in = self._credential_authenticate(email, password, kwargs.get('servers') or [self.default_server])

        if not logged_in:
            self.logger.critical('All login methods failed. Cannot log in to SE.')
            raise LoginError('All available login methods failed.')
        else:
            self._authed_servers = kwargs.get('servers') or [self.default_server]
            return self.session

    def join(self, room_id, server):
        """
        Join a room and start processing events from it.
        :param room_id: the ID of the room you wish to join
        :param server: the server on which the room is hosted
        :return: None
        """
        if server not in self._authed_servers:
            raise InvalidOperationError('Cannot join a room on a host we haven\'t authenticated to!')

        room = Room(server, room_id=room_id)
        self.rooms.append(room)

        self.session.get("https://chat.{}/rooms/{}".format(server, room_id), data={'fkey': self._fkeys[server]})

        events = self.session.post("https://chat.{}/chats/{}/events".format(server, room_id), data={
            'fkey': self._fkeys[server],
            'since': 0,
            'mode': 'Messages',
            'msgCount': 100
        }).json()['events']

        event_data = [Event(x, server) for x in events]
        room.add_events(event_data)

        ws_auth_data = self.session.post("https://chat.{}/ws-auth".format(server), data={
            'fkey': self._fkeys[server],
            'roomid': room_id
        }).json()

        cookie_string = ''
        for cookie in self.session.cookies:
            if cookie.domain == 'chat.{}'.format(server) or cookie.domain == '.{}'.format(server):
                cookie_string += '{}={};'.format(cookie.name, cookie.value)

        last_event_time = sorted(events, key=lambda x: x['time_stamp'])[-1]['time_stamp']
        ws_uri = '{}?l={}'.format(ws_auth_data['url'], last_event_time)
        if server in self._sockets and self._sockets[server].open:
            self._sockets[server].close()

        self._sockets[server] = WSClient(ws_uri, cookie_string, server, self._on_message)

    def send(self, content, room=None, server=None):
        """
        Send a message to the specified room.
        :param content: the contents of the message you wish to send
        :param room: the ID of the room you wish to send it to
        :param server: the server on which the room is hosted
        :return: None
        """
        if room is None or server is None:
            raise InvalidOperationError('Cannot send a message to a non-existent room or a non-existent server.')

        # TODO

    def add_handler(self, handler, **kwargs):
        """
        Add an event handler for messages received from the chat websocket.
        :param handler: the handler method to call for each received event
        :return: None
        """
        self._handlers.append([handler, kwargs])

    def _credential_authenticate(self, email, password, servers):
        """
        Authenticate with Stack Exchange using provided credentials.
        :param email: the email of the Stack Exchange account you want to log in as
        :param password: the corresponding account password
        :return: a success boolean
        """
        fkey_page = self.session.get("https://stackapps.com/users/login")
        fkey_soup = BeautifulSoup(fkey_page.text, 'html.parser')
        fkey_input = fkey_soup.select('input[name="fkey"]')
        if len(fkey_input) <= 0:
            raise LoginError('Failed to get fkey from StackApps. Wat?')

        fkey = fkey_input[0].get('value')

        login_post = self.session.post("https://stackapps.com/users/login", data={
            'email': email,
            'password': password,
            'fkey': fkey
        })
        login_soup = BeautifulSoup(login_post.text, 'html.parser')
        iframes = login_soup.find_all('iframe')
        if any(['captcha' in x.get('src') for x in iframes]):
            raise LoginError('Login triggered a CAPTCHA - cannot proceed.')

        tokens = self.session.post("https://stackapps.com/users/login/universal/request", headers={
            'Referer': 'https://stackapps.com/'
        }).json()

        for site_token in tokens:
            self.session.get("https://{}/users/login/universal.gif".format(site_token['Host']), data={
                'authToken': site_token['Token'],
                'nonce': site_token['Nonce']
            }, headers={
                'Referer': 'https://stackapps.com/'
            })

        return self._verify_login(servers)

    def _verify_login(self, servers):
        """
        Verifies that login with cached cookies has been successful for all the given chat servers.
        :param servers: a list of servers to check for successful logins
        :return: a success boolean
        """
        statuses = []
        for server in servers:
            chat_home = self.session.get("https://chat.{}/".format(server))
            chat_soup = BeautifulSoup(chat_home.text, 'html.parser')
            self._fkeys[server] = chat_soup.select('input[name="fkey"]')[0].get('value')
            topbar_links = chat_soup.select('.topbar-links span.topbar-menu-links a')
            if len(topbar_links) <= 0:
                raise LoginError('Unable to verify login because page layout wasn\'t as expected. Wat?')
            elif topbar_links[0].text == 'log in':
                raise LoginError('Failed to log in to {}'.format(server))
            else:
                statuses.append(True)

        return len(statuses) == 3 and all(statuses)

    def _on_message(self, data, server):
        data = json.loads(data)
        events = [v['e'] for k, v in data.items() if k[0] == 'r' and 'e' in v]
        events = [x for s in events for x in s]

        for event_data in events:
            event = Event(event_data, server)
            handlers = [x[0] for x in self._handlers
                        if all([k in event_data and event_data[k] == v for k, v in x[1].items()])]
            for handler in handlers:
                def run_handler():
                    handler(event, server)

                threading.Thread(name='handler_runner', target=run_handler).start()
