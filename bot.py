#!/usr/bin/python3
# coding: utf-8

import discord
from discord.ext import commands

TOKEN_FILENAME='TOKEN'

with open(TOKEN_FILENAME, 'r') as token_file:
    token = token_file.read().replace('\n','')

description = '''Bot de la tribu'''

bot = commands.Bot(command_prefix='/', description=description)

@bot.event
async def on_ready():
    print(f'Now logged in as {bot.user.name} {bot.user.id}')

@bot.event
async def on_guild_available(guild):
    print(f'Joining guild {guild}')
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
    if (guild is not None) and (author is not None) :
        if member is not None:
            original_name = member.nick
            print(f'change {original_name} to {to_name}')
            await member.edit(nick = to_name)
            await channel.send(f'{author.name} change le nom de {original_name} en {member.mention}')
        else:
            await author.send(f'Utilisateur inexistant')
        await ctx.message.delete()

bot.run(token)

