import re
import requests
from bs4 import BeautifulSoup
from stackl.helpers import Helpers
from stackl.tasks import Tasks


class Room:
    def __init__(self, server, **kwargs):
        self.id = int(kwargs.get('room_id'))
        self.server = server
        self.url = "https://chat.{}/rooms/{}".format(server, kwargs.get('room_id'))
        self.owners = []
        self.events = []

        Tasks.do(self._scrape_room_info)

    def _scrape_room_info(self):
        info_page = requests.get("https://chat.{}/rooms/info/{}".format(self.server, self.id))
        room_soup = BeautifulSoup(info_page.text, 'html.parser')
        metadata_card = room_soup.select('.roomcard-xxl')[0]
        self.name = metadata_card.find('h1').text
        self.description = metadata_card.find('p').text

        owner_cards = room_soup.select('.room-ownercards .usercard')
        for card in owner_cards:
            user_id = card.get('id').split('-')[-1]
            self.owners.append(Helpers.cached(int(user_id), 'users', lambda: User(self.server, user_id=user_id)))

        Helpers.cache(self.id, 'rooms', self)

    def add_events(self, events):
        self.events.extend(events)


class User:
    def __init__(self,  server, **kwargs):
        self.id = int(kwargs.get('user_id'))
        self.server = server
        self.url = "https://chat.{}/users/{}".format(server, kwargs.get('user_id'))
        self.in_rooms = []
        self.owns_rooms = []

        Tasks.do(self._scrape_user_info)

    def _scrape_user_info(self):
        user_page = requests.get(self.url)
        user_soup = BeautifulSoup(user_page.text, 'html.parser')

        self.username = user_soup.select('.content h1')[0].text
        self.is_moderator = '♦' in user_soup.select('.usercard-xxl .user-status')[0].text
        try:
            self.bio = user_soup.select('.user-stats tr')[3].select('td')[-1].text
        except IndexError:
            self.bio = ''

        in_room_cards = user_soup.select('#user-roomcards-container .roomcard')
        self.in_rooms.extend(self._initialize_rooms(in_room_cards))

        owns_room_cards = user_soup.select('#user-owningcards .roomcard')
        self.owns_rooms.extend(self._initialize_rooms(owns_room_cards))

        Helpers.cache(self.id, 'users', self)

    def _initialize_rooms(self, card_list):
        for room_card in card_list:
            room_id = room_card.get('id').split('-')[-1]
            yield Helpers.cached(int(room_id), 'rooms', lambda: Room(self.server, room_id=room_id))


class Message:
    def __init__(self, server, **kwargs):
        self.server = server
        self.id = int(kwargs.get('message_id'))
        self.timestamp = kwargs.get('timestamp')
        self.content = kwargs.get('content')
        self.room = Helpers.cached(int(kwargs.get('room_id')), 'rooms',
                                   lambda: Room(server, room_id=kwargs.get('room_id')))
        self.user = Helpers.cached(int(kwargs.get('user_id')), 'users',
                                   lambda: User(server, user_id=kwargs.get('user_id')))
        self.parent = (Helpers.cached(int(kwargs.get('parent_id')), 'messages',
                                      lambda: kwargs.get('client').get_message(kwargs.get('parent_id'), server))
                       if 'client' in kwargs and 'parent_id' in kwargs else None)
        self.parent_id = kwargs.get('parent_id') if 'parent_id' in kwargs and 'client' not in kwargs else None
        self._content_source = kwargs.get('content_source')

        self._setup_delegate_methods()

    def reply(self, client, content):
        client.send(':{} {}'.format(self.id, content), room=self.room, server=self.server)

    def is_reply(self):
        return re.match(r'^:\d+ ', self.content) is not None

    def get_content_source(self, client=None):
        if self._content_source is not None:
            return self._content_source
        elif client is not None:
            return client.get_message_source(self.id, self.server)
        else:
            return None

    # Less ugly than having a method for every one of these that does exactly the same thing.
    def _setup_delegate_methods(self):
        method_names = ['toggle_star', 'star_count', 'star', 'unstar', 'has_starred', 'cancel_stars', 'delete', 'edit',
                        'toggle_pin', 'pin', 'unpin', 'is_pinned']

        def create_delegate(method_name):
            def delegate(client, *args):
                getattr(client, method_name)(self.id, self.server, *args)

            return delegate

        for name in method_names:
            setattr(self, name, create_delegate(name))
