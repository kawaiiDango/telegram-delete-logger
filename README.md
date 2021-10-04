Saves deleted and edited messages to another (private) chat.
Saves deleted media by pickling the media metadata to the db.

Rename `config.py.example` to `config.py` and fill in the stuff.
The chat ids there, are bot api style ids.

- Logs a limited amount of messages at a time to reduce chances of getting a FloodWaitError.
  You probably don't want to see that spam anyways.
- Telegram doesn’t always notify the clients that a message was deleted, so it will miss some
  [telethon docs](C:\Users\arn\Dropbox\stuffs\pyweeb\telethon\tg-delete-logger)
- Telegram may not have the media after it was deleted
