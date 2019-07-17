#!/usr/bin/python3
# coding: utf-8

import discord
from discord.ext import commands
import yaml

CONFIG_FILENAME='tobman.yaml'

with open(CONFIG_FILENAME, 'r') as config_file:
    data = yaml.safe_load(config_file)
    if 'discord_api_token' not in data:
        print(f'Error: {CONFIG_FILENAME} does not define the key "token"')
    token = data['discord_api_token']
    if 'rename_allowed_channels' in data:
        rename_allowed_channels = data['rename_allowed_channels']
    else:
        renamed_allowed_channels = []

description = '''Bot de la tribu'''

bot = commands.Bot(command_prefix='/', description=description)

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

@bot.command(name='rename')
async def rename(ctx, member: discord.Member, to_name):
    print(f'Rename command: {member} -> {to_name}')
    guild = ctx.guild
    author = ctx.author
    channel = ctx.message.channel
    if (guild is not None) and (author is not None) and (channel.name in rename_allowed_channels):
        if member is not None:
            original_name = member.nick or member.name
            print(f'change {original_name} to {to_name}')
            await member.edit(nick = to_name)
            embed = discord.Embed(title = 'Changement de nom !', type = 'rich', description = f'{author.mention} change le nom de **{original_name}** en {member.mention}')
            await channel.send(embed = embed)
        else:
            await author.send(f'Utilisateur inexistant')
        await ctx.message.delete()

bot.run(token)

