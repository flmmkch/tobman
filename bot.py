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
    EVENTS_DELETE_TITLE='Événement supprimé'
    EVENTS_DELETE_DESC='Événement [**{0}**]({1}) supprimé'
    EVENTS_REACT_TITLE='Événement **{0}**'
    EVENTS_REACT_OK='{0} participe à l\'événement [**{1}**]({2})'
    EVENTS_REACT_NG='{0} ne participe pas à l\'événement [**{1}**]({2})'
    EVENTS_INFO_REMAINING_DAYS='dans {0} jour(s)'

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

class Event:
    REACTION_OK = '🆗'
    REACTION_NG = '🆖'
    REACTIONS = [REACTION_OK, REACTION_NG]
    DATE_FORMAT='%Y-%m-%d'
    def __init__(self, title):
        self.guild_id = None
        self.channel_id = None
        self.message_id = None
        self.command_message_id = None
        self.title = title
        self.message = None
        self.url_string = None
        self.description = ''
        self.date = None
    def parse_new_command(original_message, args_list):
        event = None
        embed = None
        if len(args_list) > 0:
            original_embed = None
            if original_message is not None and original_message.embeds is not None and len(original_message.embeds) > 0:
                original_embed = original_message.embeds[0]
                title = str(original_embed.title)
                event = Event(title)
                event.set_url(original_embed.url)
                event.description = original_embed.description
            else:
                event = Event(str(args_list[0]))
            if len(args_list) > 1:
                # arg 1 should be the date
                event.set_date_from_string(args_list[1])
            embed = discord.Embed(title = Translation.EVENTS_NEW_TITLE.format(event.title),
                type = 'rich',
                description = event.description
                )
            if original_embed:
                embed.url = original_embed.url
                if original_embed.thumbnail != discord.Embed.Empty:
                    embed.set_thumbnail(url = original_embed.thumbnail.url)
        return event, embed
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
            remaining_days_string = f' *{Translation.EVENTS_INFO_REMAINING_DAYS.format(remaining_days)}*'
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
        date = self.get_date_string()
        if date:
            serializable['date'] = date
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
    def get_date_string(self):
        if self.date:
            return self.date.strftime(self.DATE_FORMAT)
        return None
    def set_message(self, message):
        self.message = message
    def pending_date(self):
        if self.date:
            today = self.date.today()
            return not (today < self.date)
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
    async def refresh_channel_events(self, channel):
        if Section.list_fits(bot.tobman.events_allowed_in, channel):
            guild = channel.guild
            id_str = Event.format_room_id(guild.id, channel.id)
            event_list = self.events.get(id_str)
            if event_list is not None:
                for event in event_list:
                    try:
                        message = await channel.fetch_message(int(event.message_id))
                        event.set_message(message)
                    except Exception as err:
                        print(f'Error refreshing events for message {event.message_id}: {err}', file=sys.stderr)
    def get_events_from_ids(self, guild_id, channel_id, message_id):
        id_str = Event.format_room_id(guild_id, channel_id)
        event_list = self.events.get(id_str)
        if event_list:
            indices_to_remove = []
            return [event for event in event_list if (event.message_id == message_id)]
        else:
            return []
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
            events_to_delete = [event for event in event_list if (event.message_id == message_id or event.command_message_id == message_id)]
            if len(events_to_delete) > 0:
                for event in events_to_delete:
                    event_list.remove(event)
                self.save_data()
                channel = self.get_channel_from_ids(guild_id, channel_id, only_if_can_send = True)
                if channel:
                    for event in events_to_delete:
                        embed = discord.Embed(title = Translation.EVENTS_DELETE_TITLE, description = Translation.EVENTS_DELETE_DESC.format(event.title, event.message_url()))
                        await channel.send(embed = embed)
    async def on_event_reaction_add(self, guild_id, channel_id, message_id, user_id, emoji):
        if user_id != self.bot.user.id and emoji.name in Event.REACTIONS:
            channel = self.get_channel_from_ids(guild_id, channel_id, only_if_can_send = True)
            if channel:
                for event in self.get_events_from_ids(guild_id, channel_id, message_id):
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
            member_real_id = int(member_id[3:-1])
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
        await ctx.message.delete()

@bot.command(name='event.new')
async def event(ctx, *args):
    guild = ctx.guild
    author = ctx.author
    channel = ctx.message.channel
    if (guild is not None) and (not author.bot) and Section.list_fits(bot.tobman.events_allowed_in, channel) and len(args) > 0:
        event, embed = Event.parse_new_command(ctx.message, args)
        if event and embed:
            message = await channel.send(embed = embed)
            event.set_ids(guild.id, channel.id, message.id, ctx.message.id)
            event.set_message(message)
            bot.tobman.add_event(event)
            # default reactions
            await message.add_reaction(Event.REACTION_OK)
            await message.add_reaction(Event.REACTION_NG)
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

@bot.event
async def on_raw_message_delete(raw_delete_event):
    await bot.tobman.on_event_message_delete(raw_delete_event.guild_id, raw_delete_event.channel_id, raw_delete_event.message_id)

@bot.event
async def on_raw_reaction_add(raw_reaction_event):
    await bot.tobman.on_event_reaction_add(raw_reaction_event.guild_id, raw_reaction_event.channel_id, raw_reaction_event.message_id, raw_reaction_event.user_id, raw_reaction_event.emoji)

bot.run(bot.tobman.token)
