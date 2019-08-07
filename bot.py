#!/usr/bin/python3
# coding: utf-8
from __future__ import annotations
import discord
from discord.ext import commands
from enum import Enum
import yaml
import re

class Translation:
    UNABLE_RENAME_USER='Impossible de renommer l\'utilisateur {0}'
    RENAME_TITLE='Changement de nom !'
    RENAME_MESSAGE='{0} change le nom de **{1}** en {2}'

CONFIG_FILENAME='tobman.yaml'

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

with open(CONFIG_FILENAME, 'r') as config_file:
    data = yaml.safe_load(config_file)
    if 'discord_api_token' not in data:
        print(f'Error: {CONFIG_FILENAME} does not define the key "token"')
    token = data['discord_api_token']
    if 'rename_allowed_in' in data:
        rename_allowed_in = [Section.from_string(section_string) for section_string in data['rename_allowed_in']]
    else:
        rename_allowed_in = []

bot = commands.Bot(command_prefix='/')

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
    if (guild is not None) and (author is not None) and Section.list_fits(rename_allowed_in, channel):
        if (member is not None) and (not member.bot):
            original_name = member.nick or member.name
            print(f'Rename command: change {original_name} to {to_name}')
            await member.edit(nick = to_name)
            embed = discord.Embed(title = Translation.RENAME_TITLE, type = 'rich', description = Translation.RENAME_MESSAGE.format(author.mention, original_name, member.mention))
            await channel.send(embed = embed)
        else:
            await author.send(Translation.UNABLE_RENAME_USER.format(member_id))
        await ctx.message.delete()

bot.run(token)

