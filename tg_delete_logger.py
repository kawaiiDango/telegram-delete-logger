import logging
import pickle
import sqlite3
import asyncio
from datetime import datetime, timedelta
from typing import List, Union
import os
from asyncio.locks import Event

from telethon import events

import config
from telethon.events import NewMessage, MessageDeleted, MessageEdited
from telethon import TelegramClient
from telethon.hints import Entity
from telethon.tl.functions.messages import SaveGifRequest, SaveRecentStickerRequest
from telethon.tl.types import (
    Message,
    PeerUser,
    PeerChat,
    PeerChannel,
    DocumentAttributeSticker,
    DocumentAttributeVideo,
    MessageMediaDice,
    MessageMediaWebPage,
    MessageMediaGame,
    Document,
    InputDocument,
    DocumentAttributeAnimated
)

TYPE_USER = 1
TYPE_CHANNEL = 2
TYPE_GROUP = 3
TYPE_BOT = 4
TYPE_UNKNOWN = 0


def init_db():
    if not os.path.exists('db'):
        os.mkdir('db')

    connection = sqlite3.connect("db/messages.db")
    cursor = connection.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER, from_id INTEGER, chat_id INTEGER,
                  type INTEGER, msg_text TEXT, media BLOB, created_time TIMESTAMP, edited_time TIMESTAMP,
                  PRIMARY KEY (chat_id, id, edited_time))""")

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS messages_created_index ON messages (created_time DESC)")

    connection.commit()

    return cursor, connection


async def get_chat_type(event: Event) -> int:
    chat_type = TYPE_UNKNOWN
    if event.is_group:  # chats and megagroups
        chat_type = TYPE_GROUP
    elif event.is_channel:  # megagroups and channels
        chat_type = TYPE_CHANNEL
    elif event.is_private:
        if (await event.get_sender()).bot:
            chat_type = TYPE_BOT
        else:
            chat_type = TYPE_USER
    return chat_type


async def new_message_handler(event: Union[NewMessage.Event, MessageEdited.Event]):
    from_id = 0
    chat_id = event.chat_id
    if isinstance(event.message.peer_id, PeerUser):
        from_id = my_id if event.message.out else event.message.peer_id.user_id
        chat_id = event.message.peer_id.user_id
    elif isinstance(event.message.peer_id, PeerChannel):
        if isinstance(event.message.from_id, PeerUser):
            from_id = event.message.from_id.user_id
    elif isinstance(event.message.peer_id, PeerChat):
        if isinstance(event.message.from_id, PeerUser):
            from_id = event.message.from_id.user_id

    if from_id in config.IGNORED_IDS or chat_id in config.IGNORED_IDS:
        return

    edited_time = 0

    async with asyncio.Lock():
        if isinstance(event, MessageEdited.Event):
            edited_time = datetime.now()  # event.message.edit_date
            await edited_deleted_handler(event)

        sqlite_cursor.execute(
            "INSERT INTO messages (id, from_id, chat_id, edited_time, type, msg_text, media, created_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event.message.id,
                from_id,
                chat_id,
                edited_time,
                await get_chat_type(event),
                event.message.message,
                sqlite3.Binary(pickle.dumps(event.message.media)),
                datetime.now()))
        sqlite_connection.commit()


def load_messages_from_event(event: Union[MessageDeleted.Event, MessageEdited.Event]) -> List[Message]:
    if isinstance(event, MessageDeleted.Event):
        ids = event.deleted_ids[:config.RATE_LIMIT_NUM_MESSAGES]
    elif isinstance(event, MessageEdited.Event):
        ids = [event.message.id]

    sql_message_ids = ",".join(str(deleted_id) for deleted_id in ids)
    if event.chat_id:
        where_clause = f"WHERE chat_id = {event.chat_id} and id IN ({sql_message_ids})"
    else:
        where_clause = f"WHERE chat_id not like \"-100%\" and id IN ({sql_message_ids})"
    query = f"""SELECT * FROM (SELECT id, from_id, chat_id, msg_text, media,
            created_time FROM messages {where_clause} ORDER BY edited_time DESC)
            GROUP BY chat_id, id ORDER BY created_time ASC"""

    db_results = sqlite_cursor.execute(query).fetchall()

    messages = []
    for db_result in db_results:
        messages.append({
            "id": db_result[0],
            "from_id": db_result[1],
            "chat_id": db_result[2],
            "msg_text": db_result[3],
            "media": pickle.loads(db_result[4])
        })

    return messages


async def create_mention(user: Entity):
    if user.first_name or user.last_name:
        mention = \
            (user.first_name + " " if user.first_name else "") + \
            (user.last_name if user.last_name else "")
    elif user.username:
        mention = user.username
    elif user.phone:
        mention = user.phone
    else:
        mention = user.id

    return mention


async def edited_deleted_handler(event: Union[MessageDeleted.Event, MessageEdited.Event]):
    if isinstance(event, MessageEdited.Event) and not config.SAVE_EDITED_MESSAGES:
        return

    messages = load_messages_from_event(event)

    log_deleted_usernames = []

    for message in messages:
        if message['from_id'] in config.IGNORED_IDS or message['chat_id'] in config.IGNORED_IDS:
            return

        try:
            user = await client.get_entity(message['from_id'])
            mention_user = await create_mention(user)
        except:
            user = None
            mention_user = "Unknown"

        log_deleted_usernames.append(mention_user)

        try:
            chat = await client.get_entity(message['chat_id'])
            try:
                mention_chat = chat.title
                is_pm = False
            except AttributeError:
                mention_chat = await create_mention(chat)
                is_pm = True
        except Exception as e:
            mention_chat = "Unknown chat"
        chat_id = str(message['chat_id']).replace("-100", "")

        if isinstance(event, MessageDeleted.Event):
            if user:
                text = f"**Deleted message from: **[{mention_user}](tg://user?id={user.id})\n"
            else:
                text = f"**Deleted message from: **{mention_user}\n"

            text += f"in [{mention_chat}](t.me/c/{chat_id}/{message['id']})"
            if is_pm:
                text += " #pm"
            text += '\n'
            if message['msg_text']:
                text += "**Message:** \n" + message['msg_text']
        elif isinstance(event, MessageEdited.Event):
            if user:
                text = f"**✏Edited message from: **[{mention_user}](tg://user?id={user.id})\n"
            else:
                text = f"**✏Edited message from: **{mention_user}\n"

            text += f"in [{mention_chat}](t.me/c/{chat_id}/{message['id']})\n"

            if message['msg_text']:
                text += f"**Original message:**\n{message['msg_text']}\n\n"
            if event.message.text:
                text += f"**Edited message:**\n{event.message.text}"

        is_sticker = hasattr(message['media'], "document") and \
            message['media'].document.attributes and \
            any(isinstance(attr, DocumentAttributeSticker)
                for attr in message['media'].document.attributes)
        is_gif = hasattr(message['media'], "document") and \
            message['media'].document.attributes and \
            any(isinstance(attr, DocumentAttributeAnimated)
                for attr in message['media'].document.attributes)
        is_round_video = hasattr(message['media'], "document") and \
            message['media'].document.attributes and \
            any((isinstance(attr, DocumentAttributeVideo) and attr.round_message == True)
                for attr in message['media'].document.attributes)
        is_dice = isinstance(message['media'], MessageMediaDice)
        is_instant_view = isinstance(message['media'], MessageMediaWebPage)
        is_game = isinstance(message['media'], MessageMediaGame)

        if is_sticker or is_round_video or is_dice or is_game:
            sent_msg = await client.send_message(config.LOG_CHAT_ID, file=message['media'])
            await sent_msg.reply(text)
        elif is_instant_view:
            await client.send_message(config.LOG_CHAT_ID, text)
        else:
            await client.send_message(config.LOG_CHAT_ID, text, file=message['media'])

        if is_gif and config.DELETE_SENT_GIFS_FROM_SAVED:
            await delete_from_saved_gifs(message['media'].document)

        if is_sticker and config.DELETE_SENT_STICKERS_FROM_SAVED:
            await delete_from_saved_stickers(message['media'].document)

    if isinstance(event, MessageDeleted.Event):
        if len(event.deleted_ids) > config.RATE_LIMIT_NUM_MESSAGES and len(log_deleted_usernames):
            await client.send_message(config.LOG_CHAT_ID, f"{len(event.deleted_ids)} messages deleted. Logged {config.RATE_LIMIT_NUM_MESSAGES}.")
        logging.info(
            f"Got {len(event.deleted_ids)} deleted messages. DB has {len(messages)}. Users: {', '.join(log_deleted_usernames)}"
        )
    elif isinstance(event, MessageEdited.Event):
        logging.info(
            f"Got 1 edited message. DB has {len(messages)}. Users: {', '.join(log_deleted_usernames)}"
        )


async def delete_from_saved_gifs(gif: Document):
    await client(SaveGifRequest(
        id=InputDocument(
            id=gif.id,
            access_hash=gif.access_hash,
            file_reference=gif.file_reference
        ),
        unsave=True
    ))


async def delete_from_saved_stickers(sticker: Document):
    await client(SaveRecentStickerRequest(
        id=InputDocument(
            id=sticker.id,
            access_hash=sticker.access_hash,
            file_reference=sticker.file_reference
        ),
        unsave=True
    ))


async def delete_expired_messages():
    while True:
        now = datetime.now()
        time_user = now - timedelta(days=config.PERSIST_TIME_IN_DAYS_USER)
        time_channel = now - \
            timedelta(days=config.PERSIST_TIME_IN_DAYS_CHANNEl)
        time_group = now - timedelta(days=config.PERSIST_TIME_IN_DAYS_GROUP)
        time_bot = now - timedelta(days=config.PERSIST_TIME_IN_DAYS_BOT)
        time_unknown = now - timedelta(days=config.PERSIST_TIME_IN_DAYS_GROUP)

        sqlite_cursor.execute(
            """DELETE FROM messages WHERE (type = ? and created_time < ?) OR
            (type = ? and created_time < ?) OR
            (type = ? and created_time < ?) OR
            (type = ? and created_time < ?) OR
            (type = ? and created_time < ?)""",
            (TYPE_USER, time_user,
             TYPE_CHANNEL, time_channel,
             TYPE_GROUP, time_group,
             TYPE_BOT, time_bot,
             TYPE_UNKNOWN, time_unknown,
             ))

        logging.info(
            f"Deleted {sqlite_cursor.rowcount} expired messages from DB"
        )

        await asyncio.sleep(300)


async def init(clientp):
    global client, my_id

    client = clientp

    if config.DEBUG_MODE:
        logging.basicConfig(level="INFO")
    else:
        logging.basicConfig(level="WARNING")

    config.IGNORED_IDS.add(config.LOG_CHAT_ID)

    my_id = (await client.get_me()).id

    client.add_event_handler(new_message_handler, events.NewMessage(
        incoming=True, outgoing=config.LISTEN_OUTGOING_MESSAGES))
    client.add_event_handler(new_message_handler, events.MessageEdited())
    client.add_event_handler(edited_deleted_handler, events.MessageDeleted())

    await delete_expired_messages()

if __name__ == "__main__":
    sqlite_cursor, sqlite_connection = init_db()

    with TelegramClient('db/user', config.API_ID, config.API_HASH) as client:
        client.loop.run_until_complete(init(client))
