#!/usr/bin/python3
# coding: utf-8
from __future__ import annotations
import discord
from discord.ext import commands
from enum import Enum
import yaml
import re
import sys
import json
import os.path
import urllib, urllib.parse
import datetime
import ics
import io

class Translation:
    UNABLE_RENAME_USER='Impossible de renommer l\'utilisateur {0}'
    RENAME_TITLE='Changement de nom !'
    RENAME_MESSAGE='{0} change le nom de **{1}** en {2}'
    EVENTS_NEW_TITLE='Événement : **{0}**'
    EVENTS_NEW='Nouvel événement'
    EVENTS_NEW_ERROR='Erreur à la création de l\'événement'
    EVENTS_LIST_TITLE='Événements sur #{0}'
    EVENTS_LIST_NONE='Aucun événement sur #{0}'
    EVENTS_LIST_DESC='{1} événement(s) sur #{0}'
    EVENTS_CLEAR_TITLE='Purge des événements sur #{0}'
    EVENTS_CLEAR_DESC='{0} événement(s) supprimé(s)'
    EVENTS_DELETE_TITLE='Suppression de l\'événement'
    EVENTS_DELETE_DESC='Événement **{0}** supprimé'
    EVENTS_DELETE_TITLE='Événement supprimé'
    EVENTS_DELETE_BY='Par'
    EVENTS_DELETE_NONE='Aucun événement ne correspond à **{0}**'
    EVENTS_REACT_TITLE='Événement **{0}**'
    EVENTS_REACT_OK='{0} participe à l\'événement [{1}]({2})'
    EVENTS_REACT_NG='{0} ne participe pas à l\'événement [{1}]({2})'
    EVENTS_INFO_ADDED_BY='Ajouté par'
    EVENTS_INFO_REMAINING_DAYS='dans {0} jours'
    EVENTS_INFO_REMAINING_DAYS_TODAY='aujourd\'hui'
    EVENTS_INFO_LOCATION='Lieu'
    EVENTS_INFO_LIST_STATUS='{0} **{1}**'
    EVENTS_NEW_ERROR_DATE_FORMAT='Erreur à la création de l\'événement : la date \'{0}\' ne correspond pas au format {1}'
    EVENTS_EDIT_TITLE='Modification de l\'événement'
    EVENTS_EDIT_DESC='Événement [{0}]({1}) modifié'
    EVENTS_EDIT_BY='Par'
    EVENTS_EDIT_NONE='Aucun événement ne correspond à **{0}**'
    EVENTS_MODIFICATION='Modification'
    EVENTS_MODIFICATION_DATE='Date *{0}* ➡️ *{1}*'
    EVENTS_MODIFICATION_LOC='Lieu *{0}* ➡️ *{1}*'
    EVENTS_MODIFICATION_URL='Adresse *{0}* ➡️ *{1}*'
    EVENTS_MODIFICATION_TITLE='Titre *{0}* ➡️ *{1}*'
    EVENT_CALENDAR_FILENAME='Agenda - {0}.ics'

CONFIG_FILENAME='tobman.yaml'
DATA_JSON_FILENAME='tobman-data.json'

class SectionType(Enum):
    TEXT_CHANNEL = 1
    CATEGORY = 2

class Section:
    _section_regex = re.compile(r"""^\#([^\s]+)$""")
    def __init__(self, section_type: SectionType, section_name: str):
        self.section_type = section_type
        self.section_name = section_name
    @classmethod
    def from_string(cls, section_string) -> Section:
        match = cls._section_regex.match(section_string)
        if match:
            return Section(SectionType.TEXT_CHANNEL, match.group(1))
        return Section(SectionType.CATEGORY, section_string)
    def fits(self, discord_channel: discord.TextChannel) -> bool:
        if self.section_type == SectionType.TEXT_CHANNEL:
            return discord_channel.name == self.section_name
        if (self.section_type == SectionType.CATEGORY) and (discord_channel.category is not None):
            return discord_channel.category.name == self.section_name
        return False
    def list_fits(section_list: list, text_channel: discord.TextChannel) -> bool:
        allow_in: Section
        for allow_in in section_list:
            if allow_in.fits(text_channel):
                return True
        return False

class EventError(Enum):
    DATE_ERROR = 1

class EventModification:
    def __init__(self, message: str, old_value: str, new_value: str):
        self.message = message
        self.old_value = old_value
        self.new_value = new_value
    def __str__(self):
        if self.old_value and self.old_value != '':
            return self.message.format(self.old_value, self.new_value)
        else:
            return self.message.format('❌', self.new_value)

class Event:
    REACTION_OK = '🆗'
    REACTION_NG = '🆖'
    REACTIONS = [REACTION_OK, REACTION_NG]
    DATE_FORMAT='%Y-%m-%d'
    TITLE_PREFIX='title:'
    DATE_PREFIX='date:'
    URL_PREFIX='url:'
    LOCATION_PREFIX='loc:'
    def __init__(self, title):
        self.guild_id = None
        self.channel_id = None
        self.message_id = None
        self.command_message_id = None
        self.title = title
        self.message = None
        self.url_string = None
        self.url_thumbnail = None
        self.description = ''
        self.location = ''
        self.date = None
        self.original_user_id = None
    @classmethod
    def parse_new_command(cls, original_message, args_list):
        event = None
        if len(args_list) > 0:
            original_embed = None
            if original_message is not None and original_message.embeds is not None and len(original_message.embeds) > 0:
                original_embed = original_message.embeds[-1]
                title = str(original_embed.title)
                event = Event(title)
                event.set_url(original_embed.url)
                event.description = original_embed.description
            else:
                event = Event(str(args_list[0]))
            for arg in args_list[1:]:
                for function in [event.parse_date, event.parse_loc]:
                    mod, error = function(arg)
                    if error:
                        return None, error
                if arg.startswith(cls.URL_PREFIX):
                    event.title = str(args_list[0])
                    event.set_url(arg[len(cls.URL_PREFIX):])
            if original_embed and original_embed.thumbnail and original_embed.thumbnail.url.startswith('http'):
                event.url_thumbnail = original_embed.thumbnail.url
            elif original_embed and original_embed.image and original_embed.image.url.startswith('http'):
                event.url_thumbnail = original_embed.image.url
        return event, None
    def parse_edit_command(self, arg_list):
        for arg in arg_list:
            for function in [self.parse_title, self.parse_date, self.parse_loc, self.parse_url]:
                mod, error = function(arg)
                if mod:
                    yield mod, None
                    break
                if error:
                    yield None, error
                    break
    def parse_date(self, arg):
        if arg.startswith(self.DATE_PREFIX):
            old_date_string = self.get_date_string()
            self.set_date_from_string(arg[len(self.DATE_PREFIX):])
            date_string = self.get_date_string()
            if date_string:
                return EventModification(Translation.EVENTS_MODIFICATION_DATE, old_date_string, date_string), None
            else:
                return None, EventError.DATE_ERROR
        return None, None
    def parse_loc(self, arg):
        if arg.startswith(self.LOCATION_PREFIX):
            old_location = self.location
            self.location = arg[len(self.LOCATION_PREFIX):]
            return EventModification(Translation.EVENTS_MODIFICATION_LOC, old_location, self.location), None
        return None, None
    def parse_title(self, arg):
        if arg.startswith(self.TITLE_PREFIX):
            old_title = self.title
            self.title = arg[len(self.TITLE_PREFIX):]
            return EventModification(Translation.EVENTS_MODIFICATION_TITLE, old_title, self.title), None
        return None, None
    def parse_url(self, arg):
        if arg.startswith(self.URL_PREFIX):
            old_url = self.url_string
            event.set_url(arg[len(self.URL_PREFIX):])
            return EventModification(Translation.EVENTS_MODIFICATION_URL, old_url, event.url_string), None
        return None, None
    def format_room_id(guild_id, channel_id):
        return f'{guild_id}-{channel_id}'
    def set_ids(self, guild_id, channel_id, message_id, command_message_id):
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.message_id = message_id
        self.command_message_id = command_message_id
    def user_counts(self):
        ok_count = None
        ng_count = None
        if self.message is not None:
            ok_count = 0
            ng_count = 0
            for reaction in self.message.reactions:
                if reaction.emoji == self.REACTION_OK:
                    ok_count = reaction.count
                    if reaction.me:
                        ok_count -= 1
                elif reaction.emoji == self.REACTION_NG:
                    ng_count = reaction.count
                    if reaction.me:
                        ng_count -= 1
        return ok_count, ng_count
    def message_url(self):
        return f'https://discordapp.com/channels/{self.guild_id}/{self.channel_id}/{self.message_id}'
    def summary(self):
        remaining_days_string = ''
        remaining_days = self.remaining_days()
        if remaining_days is not None:
            if remaining_days > 0:
                remaining_days_string = f' *{Translation.EVENTS_INFO_REMAINING_DAYS.format(remaining_days)}*'
            else:
                remaining_days_string = f' *{Translation.EVENTS_INFO_REMAINING_DAYS_TODAY}*'
        if self.message is not None:
            ok_count, ng_count = self.user_counts()
            url_part = ''
            if self.url_string:
                url_netloc = urllib.parse.urlparse(self.url_string)[1]
                url_part = f' (*[{url_netloc}]({self.url_string})*)'
            return f'[**{self.title}**]({self.message_url()}){url_part}{remaining_days_string}\n{Event.REACTION_OK} **{ok_count}**\n{Event.REACTION_NG} **{ng_count}**'
        else:
            return f'[**{self.title}**]({self.message_url()}){remaining_days_string}'
    def set_url(self, url_string):
        self.url_string = url_string
    def to_serializable(self):
        serializable = { 't': self.title, 'g': self.guild_id, 'c': self.channel_id, 'm': self.message_id, 'cm': self.command_message_id }
        if self.url_string:
            serializable['url'] = self.url_string
        if self.description:
            serializable['desc'] = self.description
        if self.location:
            serializable['loc'] = self.location
        date = self.get_date_string()
        if date:
            serializable['date'] = date
        if self.url_thumbnail:
            serializable['th'] = self.url_thumbnail
        if self.original_user_id:
            serializable['ouid'] = self.original_user_id
        return serializable
    def from_deserializable(deserializable):
        try:
            if ('g' in deserializable) and ('c' in deserializable) and ('m' in deserializable) and ('t' in deserializable):
                event = Event(str(deserializable['t']))
                guild_id = int(deserializable['g'])
                channel_id = int(deserializable['c'])
                message_id = int(deserializable['m'])
                command_message_id = int(deserializable['cm'])
                event.set_ids(guild_id, channel_id, message_id, command_message_id)
                if 'url' in deserializable:
                    event.set_url(deserializable['url'])
                if 'description' in deserializable:
                    event.description = deserializable['description']
                if 'date' in deserializable:
                    event.set_date_from_string(deserializable['date'])
                if 'th' in deserializable:
                    event.url_thumbnail = str(deserializable['th'])
                if 'loc' in deserializable:
                    event.location = str(deserializable['loc'])
                if 'ouid' in deserializable:
                    event.original_user_id = int(deserializable['ouid'])
                return event
        except Exception as err:
            print(f'Error deserializing event: {json.dump(deserializable)}: {err}', file=sys.stderr)
        return None
    def set_date_from_string(self, date_string):
        self.date = None
        try:
            self.date = datetime.datetime.strptime(date_string, self.DATE_FORMAT)
        except Exception as err:
            print(f'Error reading date string {date_string}: {err}', file=sys.stderr)
        self.date = self.date.replace(hour=11, minute=59)
    def get_date_string(self):
        if self.date:
            return self.date.strftime(self.DATE_FORMAT)
        return None
    def generate_date_ics(self):
        if self.date:
            cal = ics.Calendar()
            cal_event = ics.Event()
            cal_event.name = self.title
            cal_event.begin = self.date
            cal_event.created = datetime.datetime.today()
            cal_event.description = self.description
            cal_event.location = self.location
            if self.url_string:
                cal_event.url = self.url_string
            cal_event.make_all_day()
            cal.events.add(cal_event)
            ics_memory_buffer = io.StringIO()
            ics_memory_buffer.writelines(cal)
            ics_memory_buffer.seek(0, 0)
            return ics_memory_buffer
        return None
    async def generate_discord_embed(self):
        embed = discord.Embed(title = Translation.EVENTS_NEW_TITLE.format(self.title),
            type = 'rich',
            description = self.description
        )
        if self.original_user_id:
            original_user = bot.get_user(self.original_user_id)
            if original_user:
                embed.add_field(name = Translation.EVENTS_INFO_ADDED_BY, value = original_user.mention)
        if self.date:
            embed.add_field(name = self.get_date_string(), value = Translation.EVENTS_INFO_REMAINING_DAYS.format(self.remaining_days()).capitalize())
        if self.url_string:
            embed.url = self.url_string
        if self.location != '':
            embed.add_field(name = Translation.EVENTS_INFO_LOCATION, value = self.location)
        if self.message:
            await self.generate_add_ok_ng_embed_fields(embed)
        if self.url_thumbnail:
            embed.set_thumbnail(url = self.url_thumbnail)
        return embed
    async def generate_add_ok_ng_embed_fields(self, embed):
        ok_count, ng_count = self.user_counts()
        if (ok_count > 0) or (ng_count > 0):
            ok_mentions = []
            ng_mentions = []
            for reaction in self.message.reactions:
                if reaction.emoji == self.REACTION_OK:
                    async for user in reaction.users():
                        if user.id != bot.user.id:
                            ok_mentions.append(user.mention)
                elif reaction.emoji == self.REACTION_NG:
                    async for user in reaction.users():
                        if user.id != bot.user.id:
                            ng_mentions.append(user.mention)
            if ok_count > 0:
                embed.add_field(name = Translation.EVENTS_INFO_LIST_STATUS.format(self.REACTION_OK, ok_count), value = '\n'.join(ok_mentions))
            if ng_count > 0:
                embed.add_field(name = Translation.EVENTS_INFO_LIST_STATUS.format(self.REACTION_OK, ng_count), value = '\n'.join(ng_mentions))
    async def set_message(self, message):
        self.message = message
        # Edit the message
        embed = await self.generate_discord_embed()
        await message.edit(embed = embed)
    def still_active(self):
        if self.date:
            today = self.date.today()
            return today <= self.date
        else:
            return True
    def remaining_days(self):
        if self.date:
            today = self.date.today()
            if today > self.date:
                return 0
            else:
                delta = self.date - today
                return delta.days
        return None

class Tobman:
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rename_allowed_in = []
        self.events_allowed_in = []
        self.events = {}
        self.config_filename = CONFIG_FILENAME
        self.data_filename = DATA_JSON_FILENAME
        self.remove_rename_commands = False
        self.remove_event_commands = False
    def load_config(self):
        with open(self.config_filename, 'r') as config_file:
            data = yaml.safe_load(config_file)
            if 'discord_api_token' not in data:
                print(f'Error: {self.config_filename} does not define the key "token"')
            self.token = data['discord_api_token']
            if 'rename_allowed_in' in data:
                self.rename_allowed_in = [Section.from_string(section_string) for section_string in data['rename_allowed_in']]
            if 'events_allowed_in' in data:
                self.events_allowed_in = [Section.from_string(section_string) for section_string in data['events_allowed_in']]
            if 'remove_rename_commands' in data:
                self.remove_rename_commands = bool(data['remove_rename_commands'])
            if 'remove_event_commands' in data:
                self.remove_event_commands = bool(data['remove_event_commands'])
    def load_data(self):
        import os.path
        if os.path.isfile(self.data_filename):
            with open(self.data_filename, 'r') as data_file:
                data_json = json.load(data_file)
                if data_json is not None:
                    if 'events' in data_json:
                        self.events = {}
                        for channel_id_key, event_list_json in data_json['events'].items():
                            self.events[channel_id_key] = []
                            for event_json in event_list_json:
                                event = Event.from_deserializable(event_json)
                                if event is not None:
                                    self.events[channel_id_key].append(event)
    def save_data(self):
        data_json = {}
        data_json['events'] = {}
        for channel_id_key, event_list in self.events.items():
            event_list_json = []
            if event_list is not None:
                for event in event_list:
                    event_list_json.append(event.to_serializable())
                data_json['events'][str(channel_id_key)] = event_list_json
        with open(self.data_filename, 'w') as data_file:
            json.dump(data_json, data_file)
    def add_event(self, event):
        if (event.guild_id is not None) and (event.channel_id is not None) and (event.message_id is not None):
            id_str = Event.format_room_id(event.guild_id, event.channel_id)
            if self.events.get(id_str) is None:
                self.events[id_str] = []
            self.events[id_str].append(event)
            self.save_data()
    def clear_events(self, guild_id, channel_id):
        id_str = Event.format_room_id(guild_id, channel_id)
        event_list = self.events.get(id_str)
        self.events[id_str] = None
        self.save_data()
        return event_list
    def get_event(self, guild_id, channel_id, message_id):
        id_str = Event.format_room_id(guild_id, channel_id)
        event_list = self.events.get(id_str)
        if event_list:
            return [event for event in event_list if (event.message_id == message_id)]
    def get_events_by_title(self, guild_id, channel_id, event_title):
        id_str = Event.format_room_id(guild_id, channel_id)
        event_list = self.events.get(id_str)
        for event in event_list:
            if event.title == event_title:
                yield event
    def delete_events(self, guild_id, channel_id, event_title):
        id_str = Event.format_room_id(guild_id, channel_id)
        event_list = self.events.get(id_str)
        deleted_events = []
        for event in event_list:
            if event.title == event_title:
                deleted_events.append(event)
        for event in deleted_events:
            event_list.remove(event)
            yield event
    async def refresh_channel_events(self, channel):
        if Section.list_fits(bot.tobman.events_allowed_in, channel):
            guild = channel.guild
            id_str = Event.format_room_id(guild.id, channel.id)
            event_list = self.events.get(id_str)
            if event_list is not None:
                events_to_delete = []
                for event in event_list:
                    if event.still_active():
                        try:
                            message = await channel.fetch_message(int(event.message_id))
                            await event.set_message(message)
                        except discord.NotFound:
                            print(f'Message {event.message_id} not found, deleting event {event.title}', file=sys.stderr)
                            events_to_delete.append(event)
                        except Exception as err:
                            print(f'Error refreshing events for message {event.message_id}: {err}', file=sys.stderr)
                    else:
                        events_to_delete.append(event)
                for event in events_to_delete:
                    event_list.remove(event)
                self.save_data()
    def get_channel_from_ids(self, guild_id, channel_id, only_if_can_send = False):
        channel = self.bot.get_channel(channel_id)
        if channel and ((not only_if_can_send) or channel.permissions_for(channel.guild.me).send_messages):
            return channel
        return None
    async def on_event_message_delete(self, guild_id, channel_id, message_id):
        id_str = Event.format_room_id(guild_id, channel_id)
        event_list = self.events.get(id_str)
        if event_list:
            indices_to_remove = []
            events_to_delete = [event for event in event_list if event.message_id == message_id]
            if len(events_to_delete) > 0:
                for event in events_to_delete:
                    event_list.remove(event)
                self.save_data()
                channel = self.get_channel_from_ids(guild_id, channel_id, only_if_can_send = True)
                if channel:
                    for event in events_to_delete:
                        embed = discord.Embed(title = Translation.EVENTS_DELETE_TITLE, description = Translation.EVENTS_DELETE_DESC.format(event.title))
                        await channel.send(embed = embed)
    async def on_event_reaction_add(self, guild_id, channel_id, message_id, user_id, emoji):
        if user_id != self.bot.user.id and emoji.name in Event.REACTIONS:
            channel = self.get_channel_from_ids(guild_id, channel_id, only_if_can_send = True)
            if channel:
                for event in self.get_event(guild_id, channel_id, message_id):
                    message = await channel.fetch_message(message_id)
                    await event.set_message(message)
                    member = bot.get_guild(guild_id).get_member(user_id)
                    if member:
                        desc_message = None
                        if emoji.name == Event.REACTION_OK:
                            desc_message = Translation.EVENTS_REACT_OK
                        elif emoji.name == Event.REACTION_NG:
                            desc_message = Translation.EVENTS_REACT_NG
                        embed = discord.Embed(
                            title = Translation.EVENTS_REACT_TITLE.format(event.title),
                            description = desc_message.format(member.mention, event.title, event.message_url())
                        )
                        await channel.send(embed = embed)
    async def on_event_reaction_remove(self, guild_id, channel_id, message_id, user_id, emoji):
        if user_id != self.bot.user.id and emoji.name in Event.REACTIONS:
            channel = self.get_channel_from_ids(guild_id, channel_id, only_if_can_send = True)
            if channel:
                for event in self.get_event(guild_id, channel_id, message_id):
                    # if there are no more reactions of this emoji then add it back
                    message = await channel.fetch_message(message_id)
                    await event.set_message(message)
                    if emoji.name == Event.REACTION_OK:
                        member = bot.get_guild(guild_id).get_member(user_id)
                        embed = discord.Embed(
                            title = Translation.EVENTS_REACT_TITLE.format(event.title),
                            description = Translation.EVENTS_REACT_NG.format(member.mention, event.title, event.message_url())
                        )
                        await channel.send(embed = embed)
        

bot = commands.Bot(command_prefix='/')
bot.tobman = Tobman(bot)
bot.tobman.load_config()
bot.tobman.load_data()

@bot.event
async def on_ready():
    print(f'Now logged in as {bot.user.name} {bot.user.id}')

@bot.event
async def on_guild_available(guild):
    print(f'Opened guild {guild}')
    if not guild.me.guild_permissions.manage_messages:
        print('Cannot manage messages')
    if not guild.me.guild_permissions.manage_nicknames:
        print('Cannot manage nicknames')
    await guild.me.edit(nick = bot.user.name)

@bot.command(name='rename')
async def rename(ctx, member_id, to_name):
    guild = ctx.guild
    author = ctx.author
    channel = ctx.message.channel
    member_real_id = None
    if len(member_id) >= 4:
        try:
            member_real_id = int(member_id.replace('@', '').replace('<', '').replace('!', '').replace('>', ''))
        except ValueError:
            member_real_id = None
    member = None
    if member_real_id is not None:
        member = guild.get_member(member_real_id)
    print(f'Rename command: try {member_id} ({member}) -> {to_name}') 
    if (guild is not None) and (author is not None) and Section.list_fits(bot.tobman.rename_allowed_in, channel):
        if (member is not None) and (not member.bot):
            original_name = member.nick or member.name
            print(f'Rename command: change {original_name} to {to_name}')
            await member.edit(nick = to_name)
            embed = discord.Embed(title = Translation.RENAME_TITLE, type = 'rich', description = Translation.RENAME_MESSAGE.format(author.mention, original_name, member.mention))
            await channel.send(embed = embed)
        else:
            await author.send(Translation.UNABLE_RENAME_USER.format(member_id))
        if bot.tobman.remove_rename_commands:
            await ctx.message.delete()

@bot.command(name='event.new')
async def event(ctx, *args):
    guild = ctx.guild
    author = ctx.author
    channel = ctx.message.channel
    if (guild is not None) and (not author.bot) and Section.list_fits(bot.tobman.events_allowed_in, channel) and len(args) > 0:
        event, error_type = Event.parse_new_command(ctx.message, args)
        if event:
            embed = await event.generate_discord_embed()
            ics_cal_file = event.generate_date_ics()
            if ics_cal_file:
                ics_cal_file = discord.File(ics_cal_file, filename = Translation.EVENT_CALENDAR_FILENAME.format(str(event.title)))
            message = await channel.send(embed = embed, file = ics_cal_file)
            event.set_ids(guild.id, channel.id, message.id, ctx.message.id)
            event.original_user_id = ctx.message.author.id
            bot.tobman.add_event(event)
            # default reactions
            await message.add_reaction(Event.REACTION_OK)
            await message.add_reaction(Event.REACTION_NG)
            await event.set_message(message)
            if bot.tobman.remove_event_commands:
                await ctx.message.delete()
        elif error_type == EventError.DATE_ERROR:
            error_embed = discord.Embed(title = Translation.EVENTS_NEW_ERROR, type = 'rich', description = Translation.EVENTS_NEW_ERROR_DATE_FORMAT.format(arg, Event.DATE_FORMAT))
            message = await channel.send(embed = error_embed)
        else:
            message = await channel.send(EVENTS_NEW_ERROR)

@bot.command(name='event.list')
async def event(ctx):
    guild = ctx.guild
    author = ctx.author
    channel = ctx.message.channel
    if (guild is not None) and (not author.bot) and Section.list_fits(bot.tobman.events_allowed_in, channel):
        id_str = Event.format_room_id(guild.id, channel.id)
        event_list = bot.tobman.events.get(id_str)
        if (event_list is None) or (len(event_list) == 0):
            embed = discord.Embed(title = Translation.EVENTS_LIST_TITLE.format(channel.name),
                type = 'rich',
                description = Translation.EVENTS_LIST_NONE.format(channel.name)
            )
            await channel.send(embed = embed)
        else:
            await bot.tobman.refresh_channel_events(channel)
            embed = discord.Embed(title = Translation.EVENTS_LIST_TITLE.format(channel.name),
                type = 'rich',
                description = Translation.EVENTS_LIST_DESC.format(channel.name, len(event_list))
            )
            for event in event_list:
                embed.add_field(name = event.title, value = event.summary())
            await channel.send(embed = embed)
            if bot.tobman.remove_event_commands:
                await ctx.message.delete()

@bot.command(name='event.edit')
async def event(ctx, event_title: str, *args):
    guild = ctx.guild
    author = ctx.author
    channel = ctx.message.channel
    if (guild is not None) and (not author.bot) and Section.list_fits(bot.tobman.events_allowed_in, channel):
        event_list = list(bot.tobman.get_events_by_title(guild.id, channel.id, event_title))
        if event_list and len(event_list) > 0:
            for event in event_list:
                modifications = list(event.parse_edit_command(args))
                error_count = 0
                for modification, error in modifications:
                    if error:
                        if error == EventError.DATE_ERROR:
                            error_embed = discord.Embed(title = Translation.EVENTS_NEW_ERROR, type = 'rich', description = Translation.EVENTS_NEW_ERROR_DATE_FORMAT.format(arg, Event.DATE_FORMAT))
                            message = await channel.send(embed = error_embed)
                        else:
                            print(f'Error {error} while modifying event {event.title}, command: {args}', file=sys.stderr)
                        error_count += 1
                if (len(modifications) > 0) and (error_count == 0):
                    bot.tobman.save_data()
                    try:
                        message = await channel.fetch_message(event.message_id)
                        if message:
                            await event.set_message(message)
                            new_embed = await event.generate_discord_embed()
                            # Can't attach a file to a message edit...
                            # ics_cal_file = discord.File(event.generate_date_ics(), filename = Translation.EVENT_CALENDAR_FILENAME.format(event.title))
                            await message.edit(embed = new_embed)
                    except discord.NotFound:
                        print(f'Message {event.message_id} not found, modifying event {event.title}', file=sys.stderr)
                    embed = discord.Embed(title = Translation.EVENTS_EDIT_TITLE,
                        type = 'rich',
                        description = Translation.EVENTS_EDIT_DESC.format(event.title, event.message_url())
                    )
                    embed.add_field(name = Translation.EVENTS_EDIT_BY, value = ctx.message.author.mention)
                    await event.generate_add_ok_ng_embed_fields(embed)
                    for modification, error in modifications:
                        embed.add_field(name = Translation.EVENTS_MODIFICATION, value = str(modification))
                    await channel.send(embed = embed)
                if bot.tobman.remove_event_commands:
                    await ctx.message.delete()
        else:
            embed = discord.Embed(title = Translation.EVENTS_EDIT_TITLE,
                type = 'rich',
                description = Translation.EVENTS_EDIT_NONE.format(event.title)
            )
            await channel.send(embed = embed)

@bot.command(name='event.delete')
async def event(ctx, event_title: str):
    guild = ctx.guild
    author = ctx.author
    channel = ctx.message.channel
    if (guild is not None) and (not author.bot) and Section.list_fits(bot.tobman.events_allowed_in, channel):
        event_list = list(bot.tobman.delete_events(guild.id, channel.id, event_title))
        if event_list and len(event_list) > 0:
            for event in event_list:
                try:
                    event_message = await channel.fetch_message(event.message_id)
                    await event_message.delete()
                except discord.NotFound:
                    print(f'Message {event.message_id} not found, deleting event {event.title}', file=sys.stderr)
                embed = discord.Embed(title = Translation.EVENTS_DELETE_TITLE,
                    type = 'rich',
                    description = Translation.EVENTS_DELETE_DESC.format(event.title)
                )
                embed.add_field(name = Translation.EVENTS_DELETE_BY, value = ctx.message.author.mention)
                await channel.send(embed = embed)
            if bot.tobman.remove_event_commands:
                await ctx.message.delete()
        else:
            embed = discord.Embed(title = Translation.EVENTS_DELETE_TITLE,
                type = 'rich',
                description = Translation.EVENTS_DELETE_NONE.format(event.title)
            )
            await channel.send(embed = embed)
        
@bot.command(name='event.clear')
async def event(ctx):
    guild = ctx.guild
    author = ctx.author
    channel = ctx.message.channel
    if (guild is not None) and (not author.bot) and Section.list_fits(bot.tobman.events_allowed_in, channel):
        event_list = bot.tobman.clear_events(guild.id, channel.id)
        event_count = 0
        if event_list is not None:
            event_count = len(event_list)
        embed = discord.Embed(title = Translation.EVENTS_CLEAR_TITLE.format(channel.name),
            type = 'rich',
            description = Translation.EVENTS_CLEAR_DESC.format(event_count)
        )
        await channel.send(embed = embed)
        if bot.tobman.remove_event_commands:
            await ctx.message.delete()

@bot.event
async def on_raw_message_delete(raw_delete_event):
    await bot.tobman.on_event_message_delete(raw_delete_event.guild_id, raw_delete_event.channel_id, raw_delete_event.message_id)

@bot.event
async def on_raw_reaction_add(raw_reaction_event):
    await bot.tobman.on_event_reaction_add(raw_reaction_event.guild_id, raw_reaction_event.channel_id, raw_reaction_event.message_id, raw_reaction_event.user_id, raw_reaction_event.emoji)

@bot.event
async def on_raw_reaction_remove(raw_reaction_event):
    await bot.tobman.on_event_reaction_remove(raw_reaction_event.guild_id, raw_reaction_event.channel_id, raw_reaction_event.message_id, raw_reaction_event.user_id, raw_reaction_event.emoji)

bot.run(bot.tobman.token)
