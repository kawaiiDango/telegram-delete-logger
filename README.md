- Saves deleted and edited messages to another (private) chat.
- Works for forward restricted and self destructing messages.
- To manually save forward restricted messages, send the message link(s), whitespace separated, to the logger chat. Supports t.me and tg://openmessage links.

At the time of writing, official stable telethon is still on layer 133, so you may need this fork instead

`pip install git+https://github.com/TelegramPlayGround/Telethon.git@rotcev`

Rename `config.py.example` to `config.py` and fill in the stuff.
The chat IDs there, are bot api style IDs.

- Logs a limited amount of messages at a time to reduce chances of getting a FloodWaitError.
  You probably don't want to see that spam anyways.
- Telegram [doesn’t always notify](https://docs.telethon.dev/en/latest/quick-references/events-reference.html#messagedeleted) the clients that a message was deleted, so it will miss some.
- You might not have access to the media after it was deleted


By using this piece of spaghetti, you agree to not agree with Telegram's terms of service.