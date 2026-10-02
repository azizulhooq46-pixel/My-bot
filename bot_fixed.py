"""
Omni Cave — Discord bot replacement
Python 3.10+ | discord.py 2.x

Required environment variable:
  DISCORD_TOKEN = your Discord bot token

Optional:
  PREFIX = !

Enable these intents in Discord Developer Portal > Bot:
  - Server Members Intent
  - Message Content Intent

Install dependencies:
  pip install -U discord.py Flask

This file includes:
  - Prefix + slash versions of implemented commands via hybrid_command
  - Per-server prefix, welcome, goodbye, leveling, and embed settings
  - SQLite persistence
  - Reaction roles (moderators can configure a message/emoji/role mapping)
  - Basic moderation and information commands
  - Optional Flask keep-alive endpoint for the existing Render web service setup

This is a standalone replacement template. Merge any existing AI/Gemini commands
from your old file separately if you want to retain them.
"""

import os
import random
import sqlite3
import asyncio
from threading import Thread
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

# Optional Flask web endpoint for Render. The bot itself does not need a web port
# unless your Render service is configured as a Web Service.
try:
    from flask import Flask
    from werkzeug.serving import make_server
    flask_app = Flask(__name__)

    @flask_app.get("/")
    def home():
        return "Omni Cave is online! 🤖", 200

    def start_web():
        port = int(os.getenv("PORT", "10000"))
        flask_app.run(host="0.0.0.0", port=port)
except Exception:
    flask_app = None
    def start_web():
        return


TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("TOKEN")
DEFAULT_PREFIX = os.getenv("PREFIX", "!")
DB_PATH = os.getenv("DATABASE_PATH", "omni_cave.sqlite3")

if not TOKEN:
    raise RuntimeError(
        "Missing Discord token. Set DISCORD_TOKEN in Render Environment Variables."
    )

# ---------- SQLite ----------
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row
db_lock = asyncio.Lock()

def init_db():
    with db:
        db.execute("""
        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id INTEGER PRIMARY KEY,
            prefix TEXT NOT NULL DEFAULT '!',
            welcome_channel INTEGER,
            welcome_text TEXT DEFAULT 'Welcome {mention} to **{server}**! 🎉',
            welcome_embed INTEGER NOT NULL DEFAULT 1,
            goodbye_channel INTEGER,
            goodbye_text TEXT DEFAULT 'Goodbye {name}. We will miss you! 👋',
            goodbye_embed INTEGER NOT NULL DEFAULT 1,
            level_channel INTEGER,
            level_text TEXT DEFAULT 'GG {mention}! You reached level **{level}**! 🏆',
            level_embed INTEGER NOT NULL DEFAULT 1,
            leveling_enabled INTEGER NOT NULL DEFAULT 1
        )
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS member_xp (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            xp INTEGER NOT NULL DEFAULT 0,
            level INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS reaction_roles (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            emoji TEXT NOT NULL,
            role_id INTEGER NOT NULL,
            PRIMARY KEY (guild_id, message_id, emoji)
        )
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS xp_cooldowns (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            last_time REAL NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        )
        """)

init_db()

def ensure_guild(guild_id: int):
    with db:
        db.execute(
            "INSERT OR IGNORE INTO guild_settings (guild_id, prefix) VALUES (?, ?)",
            (guild_id, DEFAULT_PREFIX),
        )

def get_settings(guild_id: int) -> sqlite3.Row:
    ensure_guild(guild_id)
    row = db.execute(
        "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)
    ).fetchone()
    return row

def set_setting(guild_id: int, key: str, value):
    allowed = {
        "prefix", "welcome_channel", "welcome_text", "welcome_embed",
        "goodbye_channel", "goodbye_text", "goodbye_embed",
        "level_channel", "level_text", "level_embed", "leveling_enabled",
    }
    if key not in allowed:
        raise ValueError("Unsupported setting")
    ensure_guild(guild_id)
    with db:
        db.execute(
            f"UPDATE guild_settings SET {key} = ? WHERE guild_id = ?",
            (value, guild_id),
        )

def make_message(template: str, member: discord.Member, level: Optional[int] = None):
    values = {
        "mention": member.mention,
        "name": discord.utils.escape_markdown(member.display_name),
        "username": discord.utils.escape_markdown(member.name),
        "server": discord.utils.escape_markdown(member.guild.name),
        "member_count": str(member.guild.member_count or 0),
        "level": str(level if level is not None else ""),
    }
    try:
        return template.format(**values)
    except (KeyError, ValueError, IndexError):
        return template

def make_embed(title: str, description: str, color=discord.Color.blurple()):
    return discord.Embed(title=title, description=description, color=color)

async def send_configured(channel_id, text, embed_enabled, title, guild, member, level=None):
    if not channel_id:
        return
    channel = guild.get_channel(int(channel_id))
    if channel is None or not hasattr(channel, "send"):
        return
    content = make_message(text, member, level)
    try:
        if embed_enabled:
            await channel.send(embed=make_embed(title, content))
        else:
            await channel.send(content)
    except (discord.Forbidden, discord.HTTPException):
        pass

# ---------- Bot setup ----------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True

class OmniCave(commands.Bot):
    async def setup_hook(self):
        # Sync global slash commands. First sync can take a little while to appear.
        try:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} slash commands.")
        except discord.HTTPException as exc:
            print(f"Slash command sync failed: {exc}")

bot = OmniCave(
    command_prefix=lambda b, m: get_settings(m.guild.id)["prefix"]
        if m.guild else DEFAULT_PREFIX,
    intents=intents,
    help_command=None,
    case_insensitive=True,
)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("Omni Cave is ready.")

@bot.event
async def on_member_join(member: discord.Member):
    settings = get_settings(member.guild.id)
    await send_configured(
        settings["welcome_channel"], settings["welcome_text"],
        bool(settings["welcome_embed"]), "Welcome!", member.guild, member
    )

@bot.event
async def on_member_remove(member: discord.Member):
    settings = get_settings(member.guild.id)
    await send_configured(
        settings["goodbye_channel"], settings["goodbye_text"],
        bool(settings["goodbye_embed"]), "Goodbye!", member.guild, member
    )

# ---------- Leveling ----------
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    settings = get_settings(message.guild.id)
    if settings["leveling_enabled"]:
        import time
        now = time.time()
        row = db.execute(
            "SELECT last_time FROM xp_cooldowns WHERE guild_id=? AND user_id=?",
            (message.guild.id, message.author.id),
        ).fetchone()
        # One XP award per user per 60 seconds, to reduce spam farming.
        if row is None or now - row["last_time"] >= 60:
            gained = random.randint(8, 15)
            xp_row = db.execute(
                "SELECT xp, level FROM member_xp WHERE guild_id=? AND user_id=?",
                (message.guild.id, message.author.id),
            ).fetchone()
            old_level = xp_row["level"] if xp_row else 0
            new_xp = (xp_row["xp"] if xp_row else 0) + gained
            new_level = int((new_xp / 100) ** 0.5)
            with db:
                db.execute("""
                    INSERT INTO member_xp (guild_id, user_id, xp, level)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(guild_id, user_id)
                    DO UPDATE SET xp=excluded.xp, level=excluded.level
                """, (message.guild.id, message.author.id, new_xp, new_level))
                db.execute("""
                    INSERT INTO xp_cooldowns (guild_id, user_id, last_time)
                    VALUES (?, ?, ?)
                    ON CONFLICT(guild_id, user_id)
                    DO UPDATE SET last_time=excluded.last_time
                """, (message.guild.id, message.author.id, now))

            if new_level > old_level:
                latest = get_settings(message.guild.id)
                await send_configured(
                    latest["level_channel"], latest["level_text"],
                    bool(latest["level_embed"]), "Level Up!", message.guild,
                    message.author, new_level
                )

    await bot.process_commands(message)

# ---------- Prefix + slash utility commands ----------
@bot.hybrid_command(name="help", description="Show Omni Cave commands.")
async def help_command(ctx: commands.Context):
    prefix = get_settings(ctx.guild.id)["prefix"] if ctx.guild else DEFAULT_PREFIX
    embed = discord.Embed(
        title="🤖 Omni Cave Help",
        description=(
            f"Prefix: `{prefix}`\n"
            "Most commands work as both prefix and slash commands.\n\n"
            "**General**\n"
            "`help`, `ping`, `serverinfo`, `userinfo`, `rank`, `leaderboard`\n\n"
            "**Settings (Manage Server)**\n"
            "`setprefix`, `welcomechannel`, `welcometext`, `welcomeembed`,\n"
            "`goodbyechannel`, `goodbyetext`, `goodbyeembed`,\n"
            "`levelchannel`, `leveltext`, `levelembed`, `leveling`, `settings`\n\n"
            "**Moderation**\n"
            "`clear`, `kick`, `ban`, `unban`\n\n"
            "**Reaction roles**\n"
            "`reactionrole`, `removereactionrole`"
        ),
        color=discord.Color.blurple(),
    )
    await ctx.send(embed=embed)

@bot.hybrid_command(name="ping", description="Check the bot's latency.")
async def ping(ctx: commands.Context):
    await ctx.send(f"🏓 Pong! `{round(bot.latency * 1000)} ms`")

@bot.hybrid_command(name="serverinfo", description="Show server information.")
@commands.guild_only()
async def serverinfo(ctx: commands.Context):
    g = ctx.guild
    embed = discord.Embed(title=g.name, color=discord.Color.blurple())
    if g.icon:
        embed.set_thumbnail(url=g.icon.url)
    embed.add_field(name="Members", value=str(g.member_count or 0))
    embed.add_field(name="Roles", value=str(len(g.roles)))
    embed.add_field(name="Text channels", value=str(len(g.text_channels)))
    embed.add_field(name="Created", value=discord.utils.format_dt(g.created_at, "D"))
    await ctx.send(embed=embed)

@bot.hybrid_command(name="userinfo", description="Show information about a member.")
@commands.guild_only()
async def userinfo(ctx: commands.Context, member: Optional[discord.Member] = None):
    member = member or ctx.author
    embed = discord.Embed(title=f"User info: {member}", color=discord.Color.blurple())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="ID", value=str(member.id))
    embed.add_field(name="Joined server", value=discord.utils.format_dt(member.joined_at, "D") if member.joined_at else "Unknown")
    embed.add_field(name="Account created", value=discord.utils.format_dt(member.created_at, "D"))
    await ctx.send(embed=embed)

@bot.hybrid_command(name="setprefix", description="Set this server's prefix.")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def setprefix(ctx: commands.Context, prefix: str):
    if not 1 <= len(prefix) <= 5 or any(ch.isspace() for ch in prefix):
        return await ctx.send("Prefix must be 1–5 characters with no spaces.")
    set_setting(ctx.guild.id, "prefix", prefix)
    await ctx.send(f"✅ Prefix updated to `{prefix}`")

# ---------- Welcome settings ----------
@bot.hybrid_command(name="welcomechannel", description="Set the welcome message channel.")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def welcomechannel(ctx: commands.Context, channel: discord.TextChannel):
    set_setting(ctx.guild.id, "welcome_channel", channel.id)
    await ctx.send(f"✅ Welcome messages will go to {channel.mention}.")

@bot.hybrid_command(name="welcometext", description="Set welcome message text.")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def welcometext(ctx: commands.Context, *, text: str):
    set_setting(ctx.guild.id, "welcome_text", text)
    await ctx.send("✅ Welcome text saved. Variables: `{mention}`, `{name}`, `{username}`, `{server}`, `{member_count}`.")

@bot.hybrid_command(name="welcomeembed", description="Turn welcome embeds on or off.")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def welcomeembed(ctx: commands.Context, enabled: bool):
    set_setting(ctx.guild.id, "welcome_embed", int(enabled))
    await ctx.send(f"✅ Welcome embeds: **{'ON' if enabled else 'OFF'}**")

# ---------- Goodbye settings ----------
@bot.hybrid_command(name="goodbyechannel", description="Set the goodbye message channel.")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def goodbyechannel(ctx: commands.Context, channel: discord.TextChannel):
    set_setting(ctx.guild.id, "goodbye_channel", channel.id)
    await ctx.send(f"✅ Goodbye messages will go to {channel.mention}.")

@bot.hybrid_command(name="goodbyetext", description="Set goodbye message text.")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def goodbyetext(ctx: commands.Context, *, text: str):
    set_setting(ctx.guild.id, "goodbye_text", text)
    await ctx.send("✅ Goodbye text saved. Variables: `{mention}`, `{name}`, `{username}`, `{server}`, `{member_count}`.")

@bot.hybrid_command(name="goodbyeembed", description="Turn goodbye embeds on or off.")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def goodbyeembed(ctx: commands.Context, enabled: bool):
    set_setting(ctx.guild.id, "goodbye_embed", int(enabled))
    await ctx.send(f"✅ Goodbye embeds: **{'ON' if enabled else 'OFF'}**")

# ---------- Leveling settings and rank ----------
@bot.hybrid_command(name="levelchannel", description="Set the level-up announcement channel.")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def levelchannel(ctx: commands.Context, channel: discord.TextChannel):
    set_setting(ctx.guild.id, "level_channel", channel.id)
    await ctx.send(f"✅ Level-up announcements will go to {channel.mention}.")

@bot.hybrid_command(name="leveltext", description="Set level-up message text.")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def leveltext(ctx: commands.Context, *, text: str):
    set_setting(ctx.guild.id, "level_text", text)
    await ctx.send("✅ Level text saved. Variables: `{mention}`, `{name}`, `{username}`, `{server}`, `{member_count}`, `{level}`.")

@bot.hybrid_command(name="levelembed", description="Turn level-up embeds on or off.")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def levelembed(ctx: commands.Context, enabled: bool):
    set_setting(ctx.guild.id, "level_embed", int(enabled))
    await ctx.send(f"✅ Level-up embeds: **{'ON' if enabled else 'OFF'}**")

@bot.hybrid_command(name="leveling", description="Enable or disable leveling.")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def leveling(ctx: commands.Context, enabled: bool):
    set_setting(ctx.guild.id, "leveling_enabled", int(enabled))
    await ctx.send(f"✅ Leveling is now **{'enabled' if enabled else 'disabled'}**.")

@bot.hybrid_command(name="rank", description="Show a member's level and XP.")
@commands.guild_only()
async def rank(ctx: commands.Context, member: Optional[discord.Member] = None):
    member = member or ctx.author
    row = db.execute(
        "SELECT xp, level FROM member_xp WHERE guild_id=? AND user_id=?",
        (ctx.guild.id, member.id),
    ).fetchone()
    xp = row["xp"] if row else 0
    level = row["level"] if row else 0
    next_level_xp = ((level + 1) ** 2) * 100
    embed = discord.Embed(title=f"🏆 {member.display_name}'s Rank", color=discord.Color.gold())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Level", value=str(level))
    embed.add_field(name="Total XP", value=str(xp))
    embed.add_field(name="XP to next level", value=str(max(0, next_level_xp - xp)))
    await ctx.send(embed=embed)

@bot.hybrid_command(name="leaderboard", description="Show the server's top 10 members by XP.")
@commands.guild_only()
async def leaderboard(ctx: commands.Context):
    rows = db.execute(
        "SELECT user_id, xp, level FROM member_xp WHERE guild_id=? ORDER BY xp DESC LIMIT 10",
        (ctx.guild.id,),
    ).fetchall()
    if not rows:
        return await ctx.send("No XP data yet. Start chatting to earn XP!")
    lines = []
    for index, row in enumerate(rows, start=1):
        lines.append(f"**{index}.** <@{row['user_id']}> — Level {row['level']} ({row['xp']} XP)")
    await ctx.send(embed=discord.Embed(title="🏆 Omni Cave Leaderboard", description="\n".join(lines), color=discord.Color.gold()))

@bot.hybrid_command(name="settings", description="Show this server's current bot settings.")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def settings(ctx: commands.Context):
    s = get_settings(ctx.guild.id)
    def channel_text(value):
        return f"<#{value}>" if value else "Not set"
    embed = discord.Embed(title=f"{ctx.guild.name} — Omni Cave Settings", color=discord.Color.blurple())
    embed.add_field(name="Prefix", value=f"`{s['prefix']}`")
    embed.add_field(name="Welcome channel", value=channel_text(s["welcome_channel"]))
    embed.add_field(name="Welcome embed", value="On" if s["welcome_embed"] else "Off")
    embed.add_field(name="Goodbye channel", value=channel_text(s["goodbye_channel"]))
    embed.add_field(name="Goodbye embed", value="On" if s["goodbye_embed"] else "Off")
    embed.add_field(name="Level channel", value=channel_text(s["level_channel"]))
    embed.add_field(name="Level embed", value="On" if s["level_embed"] else "Off")
    embed.add_field(name="Leveling", value="On" if s["leveling_enabled"] else "Off")
    await ctx.send(embed=embed)

# ---------- Moderation ----------
@bot.hybrid_command(name="clear", description="Delete a number of recent messages.")
@commands.guild_only()
@commands.has_guild_permissions(manage_messages=True)
@commands.bot_has_guild_permissions(manage_messages=True, read_message_history=True)
async def clear(ctx: commands.Context, amount: int):
    if not 1 <= amount <= 100:
        return await ctx.send("Choose an amount between 1 and 100.")
    if ctx.interaction:
        await ctx.interaction.response.defer(ephemeral=True)
    deleted = await ctx.channel.purge(limit=amount)
    message = f"🧹 Deleted {len(deleted)} messages."
    if ctx.interaction:
        await ctx.interaction.followup.send(message, ephemeral=True)
    else:
        await ctx.send(message)

@bot.hybrid_command(name="kick", description="Kick a member from the server.")
@commands.guild_only()
@commands.has_guild_permissions(kick_members=True)
@commands.bot_has_guild_permissions(kick_members=True)
async def kick(ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided"):
    if member == ctx.author:
        return await ctx.send("You cannot kick yourself.")
    await member.kick(reason=f"{reason} | By {ctx.author}")
    await ctx.send(f"👢 Kicked {member.mention}. Reason: {reason}")

@bot.hybrid_command(name="ban", description="Ban a member from the server.")
@commands.guild_only()
@commands.has_guild_permissions(ban_members=True)
@commands.bot_has_guild_permissions(ban_members=True)
async def ban(ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided"):
    if member == ctx.author:
        return await ctx.send("You cannot ban yourself.")
    await member.ban(reason=f"{reason} | By {ctx.author}")
    await ctx.send(f"🔨 Banned **{member}**. Reason: {reason}")

@bot.hybrid_command(name="unban", description="Unban a user by their numeric Discord ID.")
@commands.guild_only()
@commands.has_guild_permissions(ban_members=True)
@commands.bot_has_guild_permissions(ban_members=True)
async def unban(ctx: commands.Context, user_id: str):
    try:
        uid = int(user_id)
        user = await bot.fetch_user(uid)
        await ctx.guild.unban(user, reason=f"By {ctx.author}")
        await ctx.send(f"✅ Unbanned {user}.")
    except ValueError:
        await ctx.send("Please provide a numeric Discord user ID.")
    except discord.NotFound:
        await ctx.send("That user is not currently banned or could not be found.")

# ---------- Reaction roles ----------
@bot.hybrid_command(name="reactionrole", description="Add an emoji reaction role to a message.")
@commands.guild_only()
@commands.has_guild_permissions(manage_roles=True, manage_messages=True)
@commands.bot_has_guild_permissions(manage_roles=True, read_message_history=True, add_reactions=True)
async def reactionrole(
    ctx: commands.Context,
    channel: discord.TextChannel,
    message_id: str,
    emoji: str,
    role: discord.Role,
):
    if role.is_default() or role.managed:
        return await ctx.send("That role cannot be assigned by a reaction role.")
    if role >= ctx.guild.me.top_role:
        return await ctx.send("Move my bot role above the role you want me to assign.")
    try:
        msg = await channel.fetch_message(int(message_id))
        await msg.add_reaction(emoji)
    except ValueError:
        return await ctx.send("Message ID must be numeric.")
    except discord.NotFound:
        return await ctx.send("I couldn't find that message in that channel.")
    except discord.HTTPException:
        return await ctx.send("I couldn't add that emoji. Check the emoji and my permissions.")
    with db:
        db.execute("""
            INSERT OR REPLACE INTO reaction_roles
            (guild_id, channel_id, message_id, emoji, role_id)
            VALUES (?, ?, ?, ?, ?)
        """, (ctx.guild.id, channel.id, int(message_id), emoji, role.id))
    await ctx.send(f"✅ Reaction role saved: {emoji} → {role.mention} on [that message]({msg.jump_url}).")

@bot.hybrid_command(name="removereactionrole", description="Remove a configured reaction role.")
@commands.guild_only()
@commands.has_guild_permissions(manage_roles=True, manage_messages=True)
async def removereactionrole(
    ctx: commands.Context,
    message_id: str,
    emoji: str,
):
    try:
        mid = int(message_id)
    except ValueError:
        return await ctx.send("Message ID must be numeric.")
    with db:
        cur = db.execute("""
            DELETE FROM reaction_roles
            WHERE guild_id=? AND message_id=? AND emoji=?
        """, (ctx.guild.id, mid, emoji))
    if cur.rowcount:
        await ctx.send("✅ Reaction role mapping removed.")
    else:
        await ctx.send("No matching reaction role mapping was found.")

def emoji_key(emoji):
    return str(emoji)

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.guild_id is None or (bot.user and payload.user_id == bot.user.id):
        return
    row = db.execute("""
        SELECT role_id FROM reaction_roles
        WHERE guild_id=? AND message_id=? AND emoji=?
    """, (payload.guild_id, payload.message_id, emoji_key(payload.emoji))).fetchone()
    if not row:
        return
    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return
    member = guild.get_member(payload.user_id)
    role = guild.get_role(row["role_id"])
    if member and role and not member.bot:
        try:
            await member.add_roles(role, reason="Omni Cave reaction role")
        except (discord.Forbidden, discord.HTTPException):
            pass

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.guild_id is None:
        return
    row = db.execute("""
        SELECT role_id FROM reaction_roles
        WHERE guild_id=? AND message_id=? AND emoji=?
    """, (payload.guild_id, payload.message_id, emoji_key(payload.emoji))).fetchone()
    if not row:
        return
    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return
    member = guild.get_member(payload.user_id)
    role = guild.get_role(row["role_id"])
    if member and role and not member.bot:
        try:
            await member.remove_roles(role, reason="Omni Cave reaction role removed")
        except (discord.Forbidden, discord.HTTPException):
            pass

# ---------- Errors ----------
@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        return await ctx.send("❌ You don't have permission to use that command.")
    if isinstance(error, commands.BotMissingPermissions):
        return await ctx.send("❌ I need more permissions to do that.")
    if isinstance(error, commands.MissingRequiredArgument):
        return await ctx.send(f"❌ Missing argument: `{error.param.name}`. Try `{get_settings(ctx.guild.id)['prefix'] if ctx.guild else DEFAULT_PREFIX}help`.")
    if isinstance(error, commands.BadArgument):
        return await ctx.send("❌ One of those arguments is invalid. Check the command's required options.")
    print(f"Command error: {type(error).__name__}: {error}")
    try:
        await ctx.send("⚠️ Something went wrong while running that command.")
    except discord.HTTPException:
        pass

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: Exception):
    original = getattr(error, "original", error)
    if isinstance(original, (commands.MissingPermissions, app_commands.MissingPermissions)):
        message = "❌ You don't have permission to use that command."
    elif isinstance(original, commands.BotMissingPermissions):
        message = "❌ I need more permissions to do that."
    else:
        print(f"Slash command error: {type(original).__name__}: {original}")
        message = "⚠️ Something went wrong while running that command."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass

async def main():
    if flask_app is not None:
        Thread(target=start_web, daemon=True).start()
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
