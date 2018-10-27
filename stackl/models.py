import requests
from bs4 import BeautifulSoup
from stackl.helpers import Helpers
from stackl.tasks import Tasks


class Room:
    def __init__(self, room_id, server):
        self.id = int(room_id)
        self.server = server
        self.url = "https://chat.{}/rooms/{}".format(server, room_id)
        self.owners = []

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
            self.owners.append(Helpers.cached(int(user_id), 'users', lambda: User(user_id, self.server)))

        Helpers.cache(self.id, 'rooms', self)


class User:
    def __init__(self, user_id, server):
        self.id = int(user_id)
        self.server = server
        self.url = "https://chat.{}/users/{}".format(server, user_id)
        self.in_rooms = []
        self.owns_rooms = []

        Tasks.do(self._scrape_user_info)

    def _scrape_user_info(self):
        user_page = requests.get(self.url)
        user_soup = BeautifulSoup(user_page.text, 'html.parser')

        self.username = user_soup.select('.usercard-xxl .user-status')[0].text
        self.bio = user_soup.select('.user-stats tr')[3].select('td')[-1].text

        in_room_cards = user_soup.select('#user-roomcards-container .roomcard')
        self.in_rooms.extend(self._initialize_rooms(in_room_cards))

        owns_room_cards = user_soup.select('#user-owningcards .roomcard')
        self.owns_rooms.extend(self._initialize_rooms(owns_room_cards))

        Helpers.cache(self.id, 'users', self)

    def _initialize_rooms(self, card_list):
        for room_card in card_list:
            room_id = room_card.get('id').split('-')[-1]
            yield Helpers.cached(int(room_id), 'rooms', lambda: Room(room_id, self.server))


class Message:
    def __init__(self, server, message_id, timestamp, content, room_id, user_id, parent_id=None):
        self.server = server
        self.id = int(message_id)
        self.timestamp = timestamp
        self.content = content
        self.room = Helpers.cached(int(room_id), 'rooms', lambda: Room(room_id, server))
        self.user = Helpers.cached(int(user_id), 'users', lambda: User(user_id, server))
        self.parent_id = parent_id

        self._setup_delegate_methods()

    def reply(self, client, content):
        client.send(':{} {}'.format(self.id, content), room=self.room, server=self.server)

    def is_reply(self):
        return re.match(r'^:\d+ ', self.content) is not None

    # Less ugly than having a method for every one of these that does exactly the same thing.
    def _setup_delegate_methods(self):
        method_names = ['toggle_star', 'star_count', 'star', 'unstar', 'has_starred', 'cancel_stars', 'delete', 'edit',
                        'toggle_pin', 'pin', 'unpin', 'is_pinned']

        def create_delegate(method_name):
            def delegate(client):
                getattr(client, method_name)(self.id, self.server)

            return delegate

        for name in method_names:
            setattr(self, name, create_delegate(name))
