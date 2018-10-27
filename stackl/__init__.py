import sys
import threading
from logging import StreamHandler
import logging
import os.path
import re
import pickle
import json
import requests
from bs4 import BeautifulSoup
from stackl.errors import LoginError, InvalidOperationError
from stackl.models import Room, Message
from stackl.events import Event
from stackl.wsclient import WSClient


VERSION = '0.0.4'


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
        self._ids = {}

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

    def id(self, server):
        """
        Get the ID of the logged-in user on the specified server.
        :param server: the chat server from which to return a user ID
        :return: Integer
        """
        return self._ids[server]

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

    def send(self, content, room=None, room_id=None, server=None):
        """
        Send a message to the specified room.
        :param content: the contents of the message you wish to send
        :param room: the ID of the room you wish to send it to
        :param server: the server on which the room is hosted
        :return: None
        """
        if (room is None and room_id is None) or server is None:
            raise InvalidOperationError('Cannot send a message to a non-existent room or a non-existent server.')

        if "\n" not in content and len(content) > 500:
            raise ValueError('Single-line messages must be a maximum of 500 chars long.')

        room_id = room_id or room.id
        for i in range(1, 3):
            response = self.session.post('https://chat.{}/chats/{}/messages/new'.format(server, room_id), data={
                'fkey': self._fkeys[server],
                'text': content
            })
            if response.status_code == 200:
                break
            elif i == 3:
                raise RuntimeError('Failed to send message. No, I don\'t know why.')

        message_data = response.json()
        parent_match = re.match(r'^:(\d+) ', content)
        message = Message(server, message_id=message_data['id'], timestamp=message_data['time'], content=content,
                          room_id=room_id, user_id=self._ids[server],
                          parent_id=None if parent_match is None else parent_match[1])
        return message

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
                self._ids[server] = int(re.match(r'/users/(\d+)', topbar_links[0].get('href'))[1])

        return len(statuses) == 3 and all(statuses)

    def _on_message(self, data, server):
        """
        Internal. Handler passed to WSClient to handle incoming websocket data before it reaches the client application.
        :param data: the raw text data received from the websocket
        :param server: the server on which the message was received
        :return: None
        """
        data = json.loads(data)
        events = [v['e'] for k, v in data.items() if k[0] == 'r' and 'e' in v]
        events = [x for s in events for x in s]

        for event_data in events:
            event = Event(event_data, server, self)
            handlers = [x[0] for x in self._handlers
                        if all([k in event_data and event_data[k] == v for k, v in x[1].items()])]
            for handler in handlers:
                def run_handler():
                    handler(event, server)

                threading.Thread(name='handler_runner', target=run_handler).start()

    def _chat_post_fkeyed(self, server, path, data=None):
        """
        Sends a POST request to chat to perform an action, automatically inserting the chat server and fkey.
        :param server: the server on which to perform the action
        :param path: the host-less path to send the request to
        :return: requests.Response
        """
        req_data = {'fkey': self._fkeys[server]}
        if data is not None:
            req_data.update(data)
        return self.session.post('https://chat.{}{}'.format(server, path), data=req_data)

    def get_message(self, message_id, server):
        soup = BeautifulSoup(self.session.get('https://chat.{}/transcript/message/{}'.format(server, message_id)).text,
                             'html.parser')
        message = soup.select('#message-{}'.format(message_id))
        user_id = re.match(r'/users/(\d+)', message.parent.parent.select('.signature .username a')[0].get('href'))[1]
        room_id = re.match(r'/rooms/(\d+)', soup.select('.room-name a')[0].get('href'))[1]
        content = self.session.get('https://chat.{}/message/{}?plain=true'.format(server, message_id)).text
        return Message(server, message_id=message_id, room_id=room_id, user_id=user_id, content=content)

    def toggle_star(self, message_id, server):
        self._chat_post_fkeyed(server, '/messages/{}/star'.format(message_id))

    def star_count(self, message_id, server):
        star_soup = BeautifulSoup(self.session.get('https://chat.{}/transcript/message/{}'.format(server, message_id)),
                                  'html.parser')
        counter = star_soup.select('#message-{} .flash .star .times'.format(message_id))
        if len(counter) > 0:
            return int(counter[0].text)
        else:
            return 0

    def star(self, message_id, server):
        if not self.has_starred(message_id, server):
            self.toggle_star(message_id, server)

    def unstar(self, message_id, server):
        if self.has_starred(message_id, server):
            self.toggle_star(message_id, server)

    def has_starred(self, message_id, server):
        star_soup = BeautifulSoup(self.session.get('https://chat.{}/transcript/message/{}'
                                                   .format(server, message_id)).text,
                                  'html.parser')
        counter = star_soup.select('#message-{} .flash .stars'.format(message_id))
        return len(counter) > 0 and 'user-star' in counter[0].get('class')

    def cancel_stars(self, message_id, server):
        self._chat_post_fkeyed(server, '/messages/{}/unstar'.format(message_id))

    def delete(self, message_id, server):
        self._chat_post_fkeyed(server, '/messages/{}/delete'.format(message_id))

    def edit(self, message_id, server, new_content):
        self._chat_post_fkeyed(server, '/messages/{}'.format(message_id), data={'text': new_content})

    def toggle_pin(self, message_id, server):
        self._chat_post_fkeyed(server, '/messages/{}/owner-star'.format(message_id))

    def pin(self, message_id, server):
        if not self.is_pinned(message_id, server):
            self.toggle_pin(message_id, server)

    def unpin(self, message_id, server):
        if self.is_pinned(message_id, server):
            self.toggle_pin(message_id, server)

    def is_pinned(self, message_id, server):
        star_soup = BeautifulSoup(self.session.get('https://chat.{}/transcript/message/{}'
                                                   .format(server, message_id)).text,
                                  'html.parser')
        counter = star_soup.select('#message-{} .flash .stars'.format(message_id))
        return len(counter) > 0 and 'owner-star' in counter[0].get('class')
