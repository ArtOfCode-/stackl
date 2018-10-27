# stackl
Python library for connecting to Stack Exchange chat.

## Installation
It's on PyPI.

    pip3 install stackl

Stackl is targeted to support Python 3, and built against Python 3.6. It almost certainly doesn't support Python 2,
though I haven't actually tested it, and may break on lower versions of Python 3. Support requests/bug reports will only
be accepted for versions at or over Python 3.5.

## Usage/Examples
The basic premise: import, create a chat client, and use that to send/receive messages.

```python
import stackl


client = stackl.ChatClient()

# Log in to just chat.stackexchange.com and chat.stackoverflow.com; ignore chat.meta.stackexchange.com.
client.login('me@example.com', 'secure-password123', servers=['stackexchange.com', 'stackoverflow.com'])

client.join(11540, 'stackexchange.com')

def handler(event, server):
    print("Received event type '{}' in room {} ({}) on server {}.".format(event.shorthand, event.room.id,
                                                                          event.room.name, server))


# Redundant in this _particular_ case, but this handler will only receive events from
# room 11540. You can use this principle to filter event handlers based on any property
# available in the websocket event data dict - more on that later.
client.add_handler(handler, room_id=11540)
```

### Log in with cookies
If you save the cookies that you get from Stack Exchange, you can use those to log in again next time without going
through credential authentication. This is not only faster, but also helps to avoid getting hit with CAPTCHAs, which
are a massive pain.

Specify `cookie_file` in your call to `ChatClient.login` to do this. If the file exists and is a valid cookie jar, it
will be applied to the client's session. The `login` call returns this logged-in session - you are responsible for
saving the cookies, so after your first credential auth you'll want to make sure you pickle and save them.

```python
import stackl
import pickle


client = stackl.ChatClient()
session = client.login('me@example.com', 'secure-password123', cookie_file='cookies.p')

with open('cookies.p', 'wb') as f:
    pickle.dump(session.cookies, f, protocol=pickle.HIGHEST_PROTOCOL)
```

### Filter event handlers
If you want certain event handlers to only receive certain types of event, you can set filters for this when you add
the handler (via `ChatClient.add_handler`). You can filter based on any property that is sent in the WebSocket event
data - for a message, this will include `message_id`, `room_id`, `user_id`, etc - you may have to use your browser's
developer tools to figure out which fields you want, because I don't know what they all are.

```python
# Only messages in room 11540 by user 121520
client.add_handler(handler, room_id=11540, user_id=121520)

# Only message-edited events, no other types
client.add_handler(handler, event_type=2)
```

---

For more details on the API available, see the API documentation or take a look at the code.

## Contributing
Contributions are welcome. Send me a PR if you have a contribution you want to make. For major changes or API changes,
it's best to open an issue to discuss it first. In particular, anything that would require an increment of the major
version number _must_ be discussed, but don't use that as an absolute - use your common sense and if in doubt, open an
issue first.

By making a contribution you agree to license the contributed work under the MIT license and declare that you are
legally entitled to grant the said license.

## License
Stackl is licensed under the [MIT license](https://github.com/ArtOfCode-/stackl/blob/master/LICENSE.md).
