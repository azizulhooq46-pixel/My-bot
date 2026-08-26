import discord
from discord.ext import commands
from datetime import timedelta
import os
from threading import Thread
from flask import Flask
app = Flask('')


@app.route('/')
def home():
  return 'Bot is online!'


def run():
  app.run(host='0.0.0.0', port=8080)


def keep_alive():
  t = Thread(target=run)
  t.start()

# Intents
blah = discord.Intents.default()
blah.message_content = True
blah.members = True

gogagaga = commands.Bot(command_prefix='?', intents=blah)

# Warnings Data Storage
warnings_data = {}

@gogagaga.event
async def on_ready():
    print(f"Logged in as {gogagaga.user}")

@gogagaga.command()
async def ping(ctx):
    latency = round(gogagaga.latency * 1000)
    embed = discord.Embed(
        title="🏓 Pong!",
        description=f"Latency is `{latency}ms`",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed)

# Warn Command
@gogagaga.command()
@commands.has_permissions(kick_members=True)
async def warn(ctx, member: discord.Member, *, reason="No reason provided"):
    user_id = member.id
    if user_id not in warnings_data:
        warnings_data[user_id] = []
    warnings_data[user_id].append(reason)

    # চ্যানেলে দেখানোর এমবেড
    embed = discord.Embed(
        title="Warning",
        description=f"*{member} has been warned.* | {reason}",
        color=discord.Color.green(),
    )

    # ইউজারের ইনবক্সে (DM) পাঠানোর এমবেড
    dm_embed = discord.Embed(
        title=f"**WARNING FROM {ctx.guild.name}**",
        description=f"You have been warned in {ctx.guild.name} for {reason}",
        color=discord.Color.green(),
    )

    try:
        await member.send(embed=dm_embed)
    except discord.Forbidden:
        pass


    await ctx.send(embed=embed)
@gogagaga.command()
async def warnings(ctx, member: discord.Member = None):
    # যদি কোনো মেম্বার মেনশন না করা হয়, তবে যে কমান্ড দিয়েছে তার ওয়ার্নিং দেখাবে
    member = member or ctx.author
    user_id = member.id
    
    user_warns = warnings_data.get(user_id, [])
    
    if not user_warns:
        embed = discord.Embed(
            title="Warnings",
            description=f"*{member.display_name} has no warnings.*",
            color=discord.Color.blue()
        )
    else:
        warn_list = "\n".join([f"{i+1}. {reason}" for i, reason in enumerate(user_warns)])
        embed = discord.Embed(
            title=f"Warnings for {member.display_name}",
            description=f"**Total Warnings:** {len(user_warns)}\n\n{warn_list}",
            color=discord.Color.gold()
        )
        
    await ctx.send(embed=embed)


# Mute Command
@gogagaga.command()
@commands.has_permissions(kick_members=True)
async def mute(ctx, member: discord.Member, time: str = "0", *, reason: str = "No reason given"):
    try:
        time_clean = time.lower().strip()
        minutes = 0

        if time_clean.endswith(("m", "min", "mins", "minute", "minutes")):
            minutes = int("".join(filter(str.isdigit, time_clean)))
        elif time_clean.endswith(("h", "hr", "hrs", "hour", "hours")):
            minutes = int("".join(filter(str.isdigit, time_clean))) * 60
        elif time_clean.endswith(("d", "day", "days")):
            minutes = int("".join(filter(str.isdigit, time_clean))) * 1440
        else:
            minutes = int(time_clean)

        if minutes <= 0:
            await ctx.send("Please give a valid time (example: `5`, `10m`, `1h`)")
            return

        # টাইমআউট কার্যকর করা
        await member.timeout(timedelta(minutes=minutes), reason=reason)

        # ১. চ্যানেলে দেখানোর এমবেড
        embed = discord.Embed(
            title="Muted",
            description=f"*{member} has been muted for **{minutes} minutes**.* | {reason}",
            color=discord.Color.green(),
        )
        await ctx.send(embed=embed)

        # ২. ইউজারের ইনবক্সে (DM) পাঠানোর এমবেড
        dm_embed = discord.Embed(
            title=f"**MUTATION FROM {ctx.guild.name}**",
            description=f"You have been muted in {ctx.guild.name} for {time} and the reason is {reason}",
            color=discord.Color.red(),
        )
        
        try:
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            pass

    except ValueError:
        await ctx.send("Invalid time format! Use like: `5`, `10m`, `1h`, `2d`")
    except discord.Forbidden:
        embed = discord.Embed(
            title="Error",
            description="I couldn't mute this member (they are higher than me or I lack permission).",
            color=discord.Color.red(),
        )
        await ctx.send(embed=embed)
@gogagaga.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx,member:discord.Member,*,reason="No reason provided"):
	try:
		await member.ban(reason=reason)
		embed=discord.Embed(title="Banned",description=f"*{member} was banned from {ctx.guild.name}*.|{reason}",color=discord.Color.blue())
		dm=discord.Embed(title=f"**BANNED FROM {ctx.guild.name}**",description=f"You have been banned ")
	except discord.Forbidden:
		fembed=discord.Embed(title="ERROR",description="Couldn't ban member since he is higher than me or I lack permission",color=discord.Color.red())
		await ctx.send(embed=fembed)

keep_alive()
gogagaga.run(os.getenv("YOUR_TOKEN_HERE"))
