from collections import namedtuple
from stackl.models import *

EventClassData = namedtuple('EventClassData', ['id', 'classes'])
EventClass = namedtuple('EventClass', ['type', 'fields', 'target_prop'])
EventField = namedtuple('EventField', ['target_prop', 'source_prop'])

EVENT_SHORTHAND = ['message', 'edit', 'entrance', 'exit', 'rename', 'star', 'debug', 'mention', 'flag', 'delete',
                   'file', 'mod-flag', 'settings', 'gnotif', 'level', 'lnotif', 'invite', 'reply', 'move-out',
                   'move-in', 'time', 'feed', 'suspended', 'merge']

EVENT_NAME = ['Message Posted', 'Message Edited', 'User Entered', 'User Left', 'Room Name Changed', 'Message Starred',
              'Debug Message', 'User Mentioned', 'Message Flagged', 'Message Deleted', 'File Added', 'Moderator Flag',
              'User Settings Changed', 'Global Notification', 'Access Level Changed', 'User Notification',
              'Invitation', 'Message Reply', 'Message Moved Out', 'Message Moved In', 'Time Break', 'Feed Ticker',
              'User Suspended', 'User Merged']

EVENT_CLASSES = [
    EventClassData(1, [
        EventClass(Message, [
            EventField('timestamp', 'time_stamp'),
            EventField('content', None),
            EventField('room_id', None),
            EventField('user_id', None),
            EventField('message_id', None),
            EventField('parent_id', None)
        ], None)
    ]),
    EventClassData(2, [
        EventClass(Message, [
            EventField('timestamp', 'time_stamp'),
            EventField('content', None),
            EventField('room_id', None),
            EventField('user_id', None),
            EventField('message_id', None)
        ], None)
    ]),
    EventClassData(3, [
        EventClass(User, [
            EventField('user_id', 'target_user_id')
        ], None),
        EventClass(Room, [
            EventField('room_id', None)
        ], None)
    ]),
    EventClassData(4, [
        EventClass(User, [
            EventField('user_id', 'target_user_id')
        ], None),
        EventClass(Room, [
            EventField('room_id', None)
        ], None)
    ]),
    EventClassData(5, [
        EventClass(Room, [
            EventField('room_id', None)
        ], None)
    ]),
    EventClassData(8, [
        EventClass(Message, [
            EventField('timestamp', 'time_stamp'),
            EventField('content', None),
            EventField('room_id', None),
            EventField('user_id', None),
            EventField('message_id', None)
        ], None),
        EventClass(User, [
            EventField('user_id', None)
        ], 'source_user'),
        EventClass(User, [
            EventField('user_id', 'target_user_id')
        ], 'target_user')
    ]),
    EventClassData(18, [
        EventClass(Message, [
            EventField('timestamp', 'time_stamp'),
            EventField('content', None),
            EventField('room_id', None),
            EventField('user_id', None),
            EventField('message_id', None)
        ], None)
    ])
]


class Event:
    def __init__(self, event_dict, server, client):
        self.type_id = int(event_dict['event_type'])
        self.name = EVENT_NAME[self.type_id - 1]
        self.shorthand = EVENT_SHORTHAND[self.type_id - 1]
        self.raw = event_dict
        self.server = server
        self.client = client

        class_data = [x for x in EVENT_CLASSES if x.id == self.type_id]
        if len(class_data) > 0:
            class_data = class_data[0]
            for type in class_data.classes:
                clazz = type.type
                if type.target_prop is not None:
                    method_name = type.target_prop
                else:
                    method_name = type.type.__name__.lower()

                initialization_props = {}
                for field in type.fields:
                    if field.source_prop is not None:
                        if field.source_prop not in event_dict:
                            continue
                        initialization_props[field.target_prop] = event_dict[field.source_prop]
                    else:
                        if field.target_prop not in event_dict:
                            continue
                        initialization_props[field.target_prop] = event_dict[field.target_prop]

                type_object = clazz(server, **initialization_props)
                setattr(self, method_name, type_object)

        for k, v in event_dict.items():
            setattr(self, k, v)

    def __repr__(self):
        return '<Event {}>'.format(self.__dict__)
