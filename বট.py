import os
import random
import sqlite3
import asyncio
from datetime import datetime, timedelta, timezone
from threading import Thread

import discord
from discord import app_commands
from discord.ext import commands, tasks
from flask import Flask

try:
    from google import genai
except ImportError:
    genai = None


# ============================================================
# OMNI CAVE - READY-TO-UPLOAD BOT
# ============================================================
# Environment variables:
# DISCORD_TOKEN       = Discord bot token
# GEMINI_API_KEY      = Google Gemini API key (optional)
# WELCOME_CHANNEL_ID  = optional default welcome channel ID
# CHAT_CHANNEL_IDS    = optional comma-separated AI auto-chat channels
# DEV_GUILD_ID        = optional server ID for instant slash-command sync
#
# IMPORTANT:
# Enable SERVER MEMBERS INTENT and MESSAGE CONTENT INTENT
# in Discord Developer Portal -> Bot -> Privileged Gateway Intents.
# ============================================================

TOKEN = os.getenv("YOUR_TOKEN_HERE")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID", "0") or 0)

_raw_chat_channels = os.getenv("CHAT_CHANNEL_IDS", "").strip()
CHAT_CHANNEL_IDS = {
    int(x.strip())
    for x in _raw_chat_channels.split(",")
    if x.strip().isdigit()
}

DEV_GUILD_ID = int(os.getenv("DEV_GUILD_ID", "0") or 0)

if not TOKEN:
    raise SystemExit("ERROR: Set DISCORD_TOKEN in Render Environment Variables.")

# -----------------------------
# Render health server
# -----------------------------
app = Flask(__name__)

@app.get("/")
def home():
    return "Omni Cave is online! 🤖"

def run_web():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    Thread(target=run_web, daemon=True).start()


# -----------------------------
# Database
# -----------------------------
DB_FILE = "omni_cave.db"
db = sqlite3.connect(DB_FILE, check_same_thread=False)
db.row_factory = sqlite3.Row
db_lock = asyncio.Lock()

def init_db():
    with db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS warnings (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS levels (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                xp INTEGER NOT NULL DEFAULT 0,
                level INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                guild_id INTEGER PRIMARY KEY,
                welcome_channel INTEGER DEFAULT 0,
                goodbye_channel INTEGER DEFAULT 0,
                qotd_channel INTEGER DEFAULT 0
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS birthdays (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                month INTEGER NOT NULL,
                day INTEGER NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            )
        """)

init_db()


# -----------------------------
# Bot setup
# -----------------------------
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

class OmniCave(commands.Bot):
    async def setup_hook(self):
        if DEV_GUILD_ID:
            guild = discord.Object(id=DEV_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            print(f"Synced {len(synced)} slash commands to DEV_GUILD_ID {DEV_GUILD_ID}.")
        else:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} global slash commands.")

bot = OmniCave(command_prefix="!", intents=intents, help_command=None)

# -----------------------------
# Runtime state
# -----------------------------
xp_cooldowns = {}
auto_chat_cooldowns = {}
recent_joins = {}
chat_enabled = {}

# -----------------------------
# Gemini
# -----------------------------
gemini = None
if genai is not None and GEMINI_API_KEY:
    try:
        gemini = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as exc:
        print("Gemini client could not start:", exc)

GEMINI_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
]

SYSTEM_STYLE = """
You are Omni Cave, a friendly Discord community bot.
Be casual, helpful, family-friendly and concise.
Usually answer in 1-4 short sentences unless the user asks for detail.
Do not claim to be human. Do not request private information.
"""

async def ask_ai(prompt: str, extra_context: str = "") -> str:
    # Check Gemini client
    if gemini is None:
        if genai is None:
            return (
                "❌ **AI Setup Error**\n"
                "**Problem:** `google-genai` is not installed.\n\n"
                "Check your `requirements.txt`."
            )

        if not GEMINI_API_KEY:
            return (
                "❌ **AI Configuration Error**\n"
                "**Problem:** `GEMINI_API_KEY` is missing.\n\n"
                "Add `GEMINI_API_KEY` to Render → Environment Variables."
            )

        return (
            "❌ **AI Client Error**\n"
            "The Gemini client could not be initialized.\n\n"
            "Check the Render logs for the initialization error."
        )

    full_prompt = (
        f"{SYSTEM_STYLE}\n\n"
        f"{extra_context}\n\n"
        f"User:\n{prompt}"
    )

    errors = []

    # Try each model separately
    for model_name in GEMINI_MODELS:
        try:
            print(f"🤖 Trying model: {model_name}")

            response = await asyncio.to_thread(
                gemini.models.generate_content,
                model=model_name,
                contents=full_prompt,
            )

            text = (getattr(response, "text", None) or "").strip()

            if text:
                print(f"✅ SUCCESS: {model_name}")
                return text[:3900]

            error = "Gemini returned an empty response."
            print(f"⚠️ {model_name}: {error}")

            errors.append(
                f"{model_name}: {error}"
            )

        except Exception as exc:
            error_type = type(exc).__name__
            error_message = str(exc)

            print("=" * 60)
            print("❌ GEMINI ERROR")
            print(f"Model: {model_name}")
            print(f"Error type: {error_type}")
            print(f"Error: {error_message}")
            print("=" * 60)

            errors.append(
                f"{model_name}\n"
                f"Type: {error_type}\n"
                f"Error: {error_message}"
            )

            continue

    # Every model failed
    error_text = "\n\n".join(errors)

    return (
        "❌ **Omni Cave AI Error**\n\n"
        "All Gemini models failed.\n\n"
        f"```text\n{error_text[:3000]}\n```\n\n"
        "🔧 Check Render logs for the complete error."
            )


# ============================================================
# DATABASE HELPERS
# ============================================================
def get_settings(guild_id):
    row = db.execute(
        "SELECT * FROM settings WHERE guild_id = ?", (guild_id,)
    ).fetchone()
    if row:
        return row
    with db:
        db.execute("INSERT OR IGNORE INTO settings (guild_id) VALUES (?)", (guild_id,))
    return db.execute(
        "SELECT * FROM settings WHERE guild_id = ?", (guild_id,)
    ).fetchone()

def xp_needed(level):
    return 100 + (level * 75)

def add_xp(guild_id, user_id, amount):
    row = db.execute(
        "SELECT xp, level FROM levels WHERE guild_id=? AND user_id=?",
        (guild_id, user_id)
    ).fetchone()

    if row:
        xp, level = row["xp"], row["level"]
    else:
        xp, level = 0, 0

    xp += amount
    leveled_up = False

    while xp >= xp_needed(level):
        xp -= xp_needed(level)
        level += 1
        leveled_up = True

    with db:
        db.execute("""
            INSERT INTO levels (guild_id, user_id, xp, level)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id)
            DO UPDATE SET xp=excluded.xp, level=excluded.level
        """, (guild_id, user_id, xp, level))

    return xp, level, leveled_up


# ============================================================
# EVENTS
# ============================================================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    await bot.change_presence(
        activity=discord.Game(name="Omni Cave • /help")
    )

    if not birthday_checker.is_running():
        birthday_checker.start()

    if not qotd_scheduler.is_running():
        qotd_scheduler.start()


@bot.event
async def on_member_join(member: discord.Member):
    if member.bot:
        return

    recent_joins[member.id] = datetime.now(timezone.utc).timestamp()
    settings = get_settings(member.guild.id)

    channel = None
    if settings["welcome_channel"]:
        channel = member.guild.get_channel(settings["welcome_channel"])

    if channel is None and WELCOME_CHANNEL_ID:
        channel = member.guild.get_channel(WELCOME_CHANNEL_ID)

    if channel is None:
        channel = member.guild.system_channel

    if channel is None:
        return

    embed = discord.Embed(
        title="👋 Welcome to Omni Cave!",
        description=(
            f"Hey {member.mention}! Welcome to **{member.guild.name}**.\n"
            "Have fun and make yourself at home! ✨"
        ),
        color=discord.Color.blurple(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"Member #{member.guild.member_count}")
    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        pass


@bot.event
async def on_member_remove(member: discord.Member):
    if member.bot:
        return

    settings = get_settings(member.guild.id)
    channel = member.guild.get_channel(settings["goodbye_channel"]) if settings["goodbye_channel"] else None

    if channel is None:
        return

    embed = discord.Embed(
        title="👋 Goodbye!",
        description=f"**{member.display_name}** has left the server.",
        color=discord.Color.orange(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        pass


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    # XP
    key = (message.guild.id, message.author.id)
    now = datetime.now(timezone.utc).timestamp()

    if now - xp_cooldowns.get(key, 0) >= 60:
        xp_cooldowns[key] = now
        xp, level, leveled_up = add_xp(
            message.guild.id, message.author.id, random.randint(10, 20)
        )

        if leveled_up:
            try:
                await message.channel.send(
                    f"🎉 {message.author.mention} reached **Level {level}**!"
                )
            except discord.Forbidden:
                pass

    # AI auto-chat / mention chat
    if message.content.startswith("!") or message.content.startswith("/"):
        return

    mentioned = bot.user in message.mentions if bot.user else False

    if mentioned:
        prompt = message.content.replace(
            f"<@{bot.user.id}>", ""
        ).replace(
            f"<@!{bot.user.id}>", ""
        ).strip()

        if not prompt:
            await message.reply("👋 Hey! I'm here. Use `/ai` to ask me something.")
            return

        reply = await ask_ai(
            prompt,
            f"Server: {message.guild.name}\nUser: {message.author.display_name}"
        )
        embed = discord.Embed(
            title="✨ Omni Cave AI",
            description=reply,
            color=discord.Color.green()
        )
        embed.set_footer(text=f"Requested by {message.author.display_name}")
        await message.reply(embed=embed)
        return

    # Optional casual auto-chat
    if CHAT_CHANNEL_IDS and message.channel.id not in CHAT_CHANNEL_IDS:
        return

    if not CHAT_CHANNEL_IDS:
        return

    channel_id = message.channel.id
    user_id = message.author.id

    if now - auto_chat_cooldowns.get((user_id, channel_id), 0) < 15:
        return

    if now - auto_chat_cooldowns.get(("channel", channel_id), 0) < 8:
        return

    if len(message.content.strip()) < 4:
        return

    if random.random() < 0.82:
        return

    auto_chat_cooldowns[(user_id, channel_id)] = now
    auto_chat_cooldowns[("channel", channel_id)] = now

    reply = await ask_ai(
        message.content,
        f"Server: {message.guild.name}. Reply casually and briefly."
    )
    try:
        await message.channel.send(reply[:1000])
    except discord.Forbidden:
        pass


# ============================================================
# BASIC SLASH COMMANDS
# ============================================================
@bot.tree.command(name="help", description="Show Omni Cave's commands")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 Omni Cave Commands",
        description="Everything you need is available with `/`.",
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="🛡️ Moderation",
        value="`/warn` `/warnings` `/clearwarnings` `/mute` `/ban` `/unban` `/role`",
        inline=False,
    )
    embed.add_field(
        name="✨ AI & Fun",
        value="`/ai` `/wave` `/ping`",
        inline=False,
    )
    embed.add_field(
        name="📈 Leveling",
        value="`/level` `/leaderboard`",
        inline=False,
    )
    embed.add_field(
        name="👋 Server",
        value="`/setwelcome` `/setgoodbye` `/chat`",
        inline=False,
    )
    embed.add_field(
        name="🎂 Birthday",
        value="`/setbirthday` `/birthday`",
        inline=False,
    )
    embed.add_field(
        name="❓ QOTD",
        value="`/setqotd` `/qotd`",
        inline=False,
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="ping", description="Check Omni Cave's latency")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 Pong! `{latency}ms`")


@bot.tree.command(name="wave", description="Wave at a member")
@app_commands.describe(member="The member to wave at")
async def wave(interaction: discord.Interaction, member: discord.Member | None = None):
    member = member or interaction.user
    await interaction.response.send_message(
        f"👋 {interaction.user.mention} waves at {member.mention}!"
    )


# ============================================================
# AI
# ============================================================
@bot.tree.command(name="ai", description="Ask Omni Cave AI a question")
@app_commands.describe(prompt="What do you want to ask?")
async def ai_command(interaction: discord.Interaction, prompt: str):
    await interaction.response.defer(thinking=True)
    reply = await ask_ai(
        prompt,
        f"Server: {interaction.guild.name if interaction.guild else 'DM'}\n"
        f"User: {interaction.user.display_name}"
    )
    embed = discord.Embed(
        title="✨ Omni Cave AI",
        description=reply,
        color=discord.Color.green()
    )
    embed.set_footer(text=f"Requested by {interaction.user.display_name}")
    await interaction.followup.send(embed=embed)


# ============================================================
# MODERATION
# ============================================================
@bot.tree.command(name="warn", description="Warn a member")
@app_commands.checks.has_permissions(kick_members=True)
@app_commands.describe(member="Member to warn", reason="Reason for the warning")
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    with db:
        db.execute(
            "INSERT INTO warnings VALUES (?, ?, ?, ?)",
            (
                interaction.guild.id,
                member.id,
                reason,
                datetime.now(timezone.utc).isoformat(),
            )
        )

    try:
        await member.send(
            f"⚠️ You were warned in **{interaction.guild.name}**.\nReason: {reason}"
        )
    except discord.Forbidden:
        pass

    await interaction.response.send_message(
        f"⚠️ {member.mention} has been warned.\n**Reason:** {reason}"
    )


@bot.tree.command(name="warnings", description="Show a member's warnings")
@app_commands.describe(member="Member to check")
async def warnings(interaction: discord.Interaction, member: discord.Member | None = None):
    member = member or interaction.user
    rows = db.execute(
        "SELECT reason, created_at FROM warnings WHERE guild_id=? AND user_id=? ORDER BY rowid",
        (interaction.guild.id, member.id)
    ).fetchall()

    if not rows:
        await interaction.response.send_message(
            f"✅ **{member.display_name}** has no warnings."
        )
        return

    text = "\n".join(
        f"**{i}.** {row['reason']}" for i, row in enumerate(rows, 1)
    )
    embed = discord.Embed(
        title=f"⚠️ Warnings • {member.display_name}",
        description=text[:4000],
        color=discord.Color.orange(),
    )
    embed.set_footer(text=f"Total warnings: {len(rows)}")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="clearwarnings", description="Clear a member's warnings")
@app_commands.checks.has_permissions(kick_members=True)
@app_commands.describe(member="Member whose warnings should be cleared")
async def clearwarnings(interaction: discord.Interaction, member: discord.Member):
    with db:
        db.execute(
            "DELETE FROM warnings WHERE guild_id=? AND user_id=?",
            (interaction.guild.id, member.id)
        )
    await interaction.response.send_message(
        f"🗑️ Cleared all warnings for {member.mention}."
    )


def parse_duration(value: str) -> int:
    value = value.lower().strip()
    units = {
        "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
        "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
        "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
        "d": 86400, "day": 86400, "days": 86400,
    }

    for suffix, multiplier in sorted(units.items(), key=lambda x: -len(x[0])):
        if value.endswith(suffix):
            number = value[:-len(suffix)].strip()
            if number.isdigit():
                return int(number) * multiplier

    if value.isdigit():
        return int(value) * 60

    raise ValueError


@bot.tree.command(name="mute", description="Timeout a member")
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.describe(member="Member to timeout", duration="Examples: 10m, 1h, 2d", reason="Reason")
async def mute(interaction: discord.Interaction, member: discord.Member, duration: str, reason: str = "No reason provided"):
    try:
        seconds = parse_duration(duration)
        if seconds <= 0 or seconds > 28 * 86400:
            raise ValueError

        await member.timeout(
            timedelta(seconds=seconds),
            reason=reason
        )
        await interaction.response.send_message(
            f"🔇 {member.mention} was muted for **{duration}**.\n**Reason:** {reason}"
        )

        try:
            await member.send(
                f"🔇 You were timed out in **{interaction.guild.name}** for **{duration}**.\nReason: {reason}"
            )
        except discord.Forbidden:
            pass

    except ValueError:
        await interaction.response.send_message(
            "❌ Invalid duration. Try `10m`, `1h`, or `2d`.",
            ephemeral=True
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ I cannot timeout that member. Check my role position and permissions.",
            ephemeral=True
        )


@bot.tree.command(name="ban", description="Ban a member")
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.describe(member="Member to ban", reason="Reason")
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    try:
        try:
            await member.send(
                f"🔨 You were banned from **{interaction.guild.name}**.\nReason: {reason}"
            )
        except discord.Forbidden:
            pass

        await member.ban(reason=reason)
        await interaction.response.send_message(
            f"🔨 **{member}** was banned.\n**Reason:** {reason}"
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ I cannot ban that member. Check my role position and permissions.",
            ephemeral=True
        )


@bot.tree.command(name="unban", description="Unban a user by ID")
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.describe(user_id="The banned user's Discord ID")
async def unban(interaction: discord.Interaction, user_id: str):
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user)
        await interaction.response.send_message(f"✅ Unbanned **{user}**.")
    except ValueError:
        await interaction.response.send_message("❌ User ID must be a number.", ephemeral=True)
    except discord.NotFound:
        await interaction.response.send_message("❌ That user can't be banned lol")
    except discord.Forbidden:
        await interaction.response.send_message("❌ I don't have permission to unban users.", ephemeral=True)


@bot.tree.command(name="role", description="Add or remove a role from a member")
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.describe(member="Member", role="Role to toggle")
async def role(interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    if role >= interaction.guild.me.top_role:
        await interaction.response.send_message(
            "❌ I cannot manage that role because it is above my highest role.",
            ephemeral=True
        )
        return

    try:
        if role in member.roles:
            await member.remove_roles(role)
            await interaction.response.send_message(
                f"➖ Removed {role.mention} from {member.mention}."
            )
        else:
            await member.add_roles(role)
            await interaction.response.send_message(
                f"➕ Added {role.mention} to {member.mention}."
            )
    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ I don't have permission to manage that role.", ephemeral=True
        )


@bot.tree.command(name="userinfo", description="Show information about a member")
@app_commands.describe(member="Member to inspect")
async def userinfo(interaction: discord.Interaction, member: discord.Member | None = None):
    member = member or interaction.user
    roles = [r.mention for r in member.roles if r != interaction.guild.default_role]

    embed = discord.Embed(
        title=f"👤 User Info • {member.display_name}",
        color=member.color if member.color.value else discord.Color.blurple(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Username", value=str(member), inline=True)
    embed.add_field(name="ID", value=str(member.id), inline=True)
    embed.add_field(
        name="Joined",
        value=discord.utils.format_dt(member.joined_at, "D") if member.joined_at else "Unknown",
        inline=True
    )
    embed.add_field(
        name="Created",
        value=discord.utils.format_dt(member.created_at, "D"),
        inline=True
    )
    embed.add_field(
        name=f"Roles ({len(roles)})",
        value=", ".join(roles)[:1000] if roles else "No roles",
        inline=False
    )
    await interaction.response.send_message(embed=embed)


# ============================================================
# LEVELING
# ============================================================
@bot.tree.command(name="level", description="Show your or another member's level")
@app_commands.describe(member="Member to check")
async def level(interaction: discord.Interaction, member: discord.Member | None = None):
    member = member or interaction.user
    row = db.execute(
        "SELECT xp, level FROM levels WHERE guild_id=? AND user_id=?",
        (interaction.guild.id, member.id)
    ).fetchone()

    xp = row["xp"] if row else 0
    lvl = row["level"] if row else 0
    needed = xp_needed(lvl)

    embed = discord.Embed(
        title=f"📈 {member.display_name}'s Level",
        color=discord.Color.blurple()
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Level", value=f"`{lvl}`", inline=True)
    embed.add_field(name="XP", value=f"`{xp} / {needed}`", inline=True)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="leaderboard", description="Show the server XP leaderboard")
async def leaderboard(interaction: discord.Interaction):
    rows = db.execute(
        "SELECT user_id, xp, level FROM levels WHERE guild_id=? ORDER BY level DESC, xp DESC LIMIT 10",
        (interaction.guild.id,)
    ).fetchall()

    if not rows:
        await interaction.response.send_message("📈 Nobody has earned XP yet!")
        return

    lines = []
    for i, row in enumerate(rows, 1):
        member = interaction.guild.get_member(row["user_id"])
        name = member.display_name if member else f"User {row['user_id']}"
        lines.append(
            f"**{i}.** {name} — Level `{row['level']}` • `{row['xp']} XP`"
        )

    embed = discord.Embed(
        title="🏆 Omni Cave Leaderboard",
        description="\n".join(lines),
        color=discord.Color.gold()
    )
    await interaction.response.send_message(embed=embed)


# ============================================================
# WELCOME / GOODBYE / CHAT SETTINGS
# ============================================================
@bot.tree.command(name="setwelcome", description="Set the welcome channel")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(channel="Channel for welcome messages")
async def setwelcome(interaction: discord.Interaction, channel: discord.TextChannel):
    get_settings(interaction.guild.id)
    with db:
        db.execute(
            "UPDATE settings SET welcome_channel=? WHERE guild_id=?",
            (channel.id, interaction.guild.id)
        )
    await interaction.response.send_message(
        f"👋 Welcome messages will now go to {channel.mention}."
    )


@bot.tree.command(name="setgoodbye", description="Set the goodbye channel")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(channel="Channel for goodbye messages")
async def setgoodbye(interaction: discord.Interaction, channel: discord.TextChannel):
    get_settings(interaction.guild.id)
    with db:
        db.execute(
            "UPDATE settings SET goodbye_channel=? WHERE guild_id=?",
            (channel.id, interaction.guild.id)
        )
    await interaction.response.send_message(
        f"👋 Goodbye messages will now go to {channel.mention}."
    )


@bot.tree.command(name="chat", description="Turn Omni Cave auto-chat on or off in this channel")
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.describe(mode="Choose on or off")
@app_commands.choices(mode=[
    app_commands.Choice(name="On", value="on"),
    app_commands.Choice(name="Off", value="off"),
])
async def chat(interaction: discord.Interaction, mode: app_commands.Choice[str]):
    chat_enabled[interaction.channel.id] = mode.value == "on"
    await interaction.response.send_message(
        f"🤖 Auto-chat is now **{mode.value}** in {interaction.channel.mention}."
    )


# ============================================================
# BIRTHDAYS
# ============================================================
@bot.tree.command(name="setbirthday", description="Set your birthday (month and day)")
@app_commands.describe(month="1-12", day="1-31")
async def setbirthday(interaction: discord.Interaction, month: int, day: int):
    try:
        datetime(2024, month, day)
    except ValueError:
        await interaction.response.send_message(
            "❌ Invalid month/day.", ephemeral=True
        )
        return

    with db:
        db.execute("""
            INSERT INTO birthdays (guild_id, user_id, month, day)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id)
            DO UPDATE SET month=excluded.month, day=excluded.day
        """, (interaction.guild.id, interaction.user.id, month, day))

    await interaction.response.send_message(
        f"🎂 Your birthday is saved as **{month:02d}/{day:02d}**!"
    )


@bot.tree.command(name="birthday", description="Show a member's saved birthday")
@app_commands.describe(member="Member to check")
async def birthday(interaction: discord.Interaction, member: discord.Member | None = None):
    member = member or interaction.user
    row = db.execute(
        "SELECT month, day FROM birthdays WHERE guild_id=? AND user_id=?",
        (interaction.guild.id, member.id)
    ).fetchone()

    if not row:
        await interaction.response.send_message(
            f"🎂 No birthday is saved for **{member.display_name}**."
        )
        return

    await interaction.response.send_message(
        f"🎂 **{member.display_name}**'s birthday is **{row['month']:02d}/{row['day']:02d}**."
    )


# ============================================================
# QOTD
# ============================================================
QOTD = [
    "If you could master one skill instantly, what would it be?",
    "What game could you play for 100 hours and still enjoy?",
    "What anime would you recommend to everyone?",
    "If you could visit any fictional world, which one?",
    "What's the best piece of advice you've ever received?",
    "What is one thing you want to accomplish this year?",
    "Would you rather have unlimited money or unlimited free time?",
    "What's your favorite movie of all time?",
    "If you could meet any fictional character, who would it be?",
    "What's a hobby you want to start?",
]

@bot.tree.command(name="setqotd", description="Set the daily QOTD channel")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(channel="Channel where QOTD will be posted")
async def setqotd(interaction: discord.Interaction, channel: discord.TextChannel):
    get_settings(interaction.guild.id)
    with db:
        db.execute(
            "UPDATE settings SET qotd_channel=? WHERE guild_id=?",
            (channel.id, interaction.guild.id)
        )
    await interaction.response.send_message(
        f"❓ Daily QOTD will be posted in {channel.mention}."
    )


@bot.tree.command(name="qotd", description="Post a random Question of the Day")
async def qotd(interaction: discord.Interaction):
    question = random.choice(QOTD)
    embed = discord.Embed(
        title="❓ Question of the Day",
        description=question,
        color=discord.Color.blurple()
    )
    embed.set_footer(text="Omni Cave QOTD")
    await interaction.response.send_message(embed=embed)


# ============================================================
# DAILY TASKS
# ============================================================
@tasks.loop(minutes=5)
async def birthday_checker():
    now = datetime.now(timezone.utc)
    # We use UTC date here. For Bangladesh, change to +6 if desired.
    month, day = now.month, now.day

    rows = db.execute(
        "SELECT guild_id, user_id FROM birthdays WHERE month=? AND day=?",
        (month, day)
    ).fetchall()

    for row in rows:
        guild = bot.get_guild(row["guild_id"])
        if not guild:
            continue

        member = guild.get_member(row["user_id"])
        if not member:
            continue

        settings = get_settings(guild.id)
        channel = (
            guild.get_channel(settings["welcome_channel"])
            if settings["welcome_channel"]
            else guild.system_channel
        )

        if channel:
            try:
                await channel.send(
                    f"🎂🎉 Happy Birthday {member.mention}! Have an amazing day! 🥳"
                )
            except discord.Forbidden:
                pass


@tasks.loop(hours=24)
async def qotd_scheduler():
    await bot.wait_until_ready()

    for guild in bot.guilds:
        settings = get_settings(guild.id)
        channel = (
            guild.get_channel(settings["qotd_channel"])
            if settings["qotd_channel"]
            else None
        )

        if channel:
            embed = discord.Embed(
                title="❓ Question of the Day",
                description=random.choice(QOTD),
                color=discord.Color.blurple()
            )
            try:
                await channel.send(embed=embed)
            except discord.Forbidden:
                pass


# ============================================================
# SLASH COMMAND ERROR HANDLER
# ============================================================
@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):
    if isinstance(error, app_commands.MissingPermissions):
        message = "❌ You don't have permission to use this command."
    elif isinstance(error, app_commands.CommandOnCooldown):
        message = "⏳ Slow down and try again shortly."
    else:
        print("Slash command error:", repr(error))
        message = "❌ Something went wrong while running that command."

    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


# ============================================================
# START
# ============================================================
# ============================================================
# SERVER / USER UTILITIES
# ============================================================

server_group = app_commands.Group(
    name="server",
    description="Server information commands"
)

@server_group.command(name="info", description="Show information about the server")
async def server_info(interaction: discord.Interaction):
    guild = interaction.guild

    embed = discord.Embed(
        title=f"🏠 {guild.name}",
        description=guild.description or "No server description.",
        color=discord.Color.blurple()
    )

    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    embed.add_field(
        name="👑 Owner",
        value=f"<@{guild.owner_id}>",
        inline=True
    )
    embed.add_field(
        name="🆔 Server ID",
        value=f"`{guild.id}`",
        inline=True
    )
    embed.add_field(
        name="👥 Members",
        value=f"`{guild.member_count}`",
        inline=True
    )
    embed.add_field(
        name="💬 Channels",
        value=f"`{len(guild.channels)}`",
        inline=True
    )
    embed.add_field(
        name="🎭 Roles",
        value=f"`{len(guild.roles)}`",
        inline=True
    )
    embed.add_field(
        name="🚀 Boost Level",
        value=f"`{guild.premium_tier}`",
        inline=True
    )
    embed.add_field(
        name="💎 Boosts",
        value=f"`{guild.premium_subscription_count}`",
        inline=True
    )
    embed.add_field(
        name="📅 Created",
        value=discord.utils.format_dt(guild.created_at, "D"),
        inline=True
    )

    await interaction.response.send_message(embed=embed)


@server_group.command(name="icon", description="Show the server icon")
async def server_icon(interaction: discord.Interaction):
    guild = interaction.guild

    if not guild.icon:
        await interaction.response.send_message(
            "❌ This server doesn't have an icon."
        )
        return

    embed = discord.Embed(
        title=f"🖼️ {guild.name} Server Icon",
        color=discord.Color.blurple()
    )
    embed.set_image(url=guild.icon.url)

    await interaction.response.send_message(embed=embed)


@server_group.command(name="roles", description="Show all server roles")
async def server_roles(interaction: discord.Interaction):
    guild = interaction.guild

    roles = [
        role.mention
        for role in reversed(guild.roles)
        if role != guild.default_role
    ]

    if not roles:
        text = "No custom roles."
    else:
        text = " ".join(roles)

    if len(text) > 4000:
        text = text[:3997] + "..."

    embed = discord.Embed(
        title=f"🎭 {guild.name} Roles",
        description=text,
        color=discord.Color.blurple()
    )

    embed.set_footer(text=f"Total roles: {len(guild.roles) - 1}")

    await interaction.response.send_message(embed=embed)


@server_group.command(name="members", description="Show server member statistics")
async def server_members(interaction: discord.Interaction):
    guild = interaction.guild

    humans = sum(1 for member in guild.members if not member.bot)
    bots = sum(1 for member in guild.members if member.bot)

    embed = discord.Embed(
        title=f"👥 {guild.name} Members",
        color=discord.Color.green()
    )

    embed.add_field(
        name="👤 Humans",
        value=f"`{humans}`",
        inline=True
    )
    embed.add_field(
        name="🤖 Bots",
        value=f"`{bots}`",
        inline=True
    )
    embed.add_field(
        name="👥 Total",
        value=f"`{guild.member_count}`",
        inline=True
    )

    await interaction.response.send_message(embed=embed)


bot.tree.add_command(server_group)


@bot.tree.command(name="setnick", description="Change a member's nickname")
@app_commands.checks.has_permissions(manage_nicknames=True)
@app_commands.describe(
    member="Member whose nickname will be changed",
    nickname="New nickname (leave empty to remove nickname)"
)
async def setnick(
    interaction: discord.Interaction,
    member: discord.Member,
    nickname: str | None = None
):
    me = interaction.guild.me

    if member == interaction.user:
        pass

    if member == interaction.guild.owner:
        await interaction.response.send_message(
            "❌ You cannot change the server owner's nickname.",
            ephemeral=True
        )
        return

    if me and member.top_role >= me.top_role:
        await interaction.response.send_message(
            "❌ I cannot change that member's nickname because their role is higher than or equal to mine.",
            ephemeral=True
        )
        return

    try:
        old_nick = member.display_name
        await member.edit(
            nick=nickname,
            reason=f"Nickname changed by {interaction.user}"
        )

        if nickname:
            await interaction.response.send_message(
                f"✏️ Changed {member.mention}'s nickname from "
                f"`{old_nick}` to `{nickname}`."
            )
        else:
            await interaction.response.send_message(
                f"✏️ Removed {member.mention}'s nickname."
            )

    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ I don't have permission to change that nickname.",
            ephemeral=True
        )


@bot.tree.command(name="avatar", description="Show a user's avatar")
@app_commands.describe(member="Member whose avatar you want to see")
async def avatar(
    interaction: discord.Interaction,
    member: discord.Member | None = None
):
    member = member or interaction.user

    embed = discord.Embed(
        title=f"🖼️ {member.display_name}'s Avatar",
        color=member.color if member.color.value else discord.Color.blurple()
    )

    embed.set_image(url=member.display_avatar.url)

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="clear", description="Delete messages from this channel")
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.describe(amount="Number of messages to delete (1-100)")
async def clear(
    interaction: discord.Interaction,
    amount: app_commands.Range[int, 1, 100]
):
    if not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message(
            "❌ This command can only be used in a text channel.",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    try:
        deleted = await interaction.channel.purge(limit=amount)

        await interaction.followup.send(
            f"🧹 Deleted **{len(deleted)}** messages.",
            ephemeral=True
        )

    except discord.Forbidden:
        await interaction.followup.send(
            "❌ I don't have permission to delete messages.",
            ephemeral=True
        )


@bot.tree.command(name="kick", description="Kick a member")
@app_commands.checks.has_permissions(kick_members=True)
@app_commands.describe(
    member="Member to kick",
    reason="Reason for the kick"
)
async def kick(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):
    if member == interaction.guild.owner:
        await interaction.response.send_message(
            "❌ You cannot kick the server owner.",
            ephemeral=True
        )
        return

    if member.top_role >= interaction.guild.me.top_role:
        await interaction.response.send_message(
            "❌ I cannot kick that member because their role is higher than or equal to mine.",
            ephemeral=True
        )
        return

    try:
        try:
            await member.send(
                f"👢 You were kicked from **{interaction.guild.name}**.\n"
                f"Reason: {reason}"
            )
        except discord.Forbidden:
            pass

        await member.kick(reason=reason)

        await interaction.response.send_message(
            f"👢 **{member}** was kicked.\n**Reason:** {reason}"
        )

    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ I couldn't kick that member.",
            ephemeral=True
        )


@bot.tree.command(name="slowmode", description="Set channel slowmode")
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.describe(
    seconds="Slowmode delay in seconds (0-21600)"
)
async def slowmode(
    interaction: discord.Interaction,
    seconds: app_commands.Range[int, 0, 21600]
):
    if not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message(
            "❌ This command can only be used in a text channel.",
            ephemeral=True
        )
        return

    try:
        await interaction.channel.edit(
            slowmode_delay=seconds,
            reason=f"Slowmode changed by {interaction.user}"
        )

        if seconds == 0:
            await interaction.response.send_message(
                "🐌 Slowmode has been **disabled**."
            )
        else:
            await interaction.response.send_message(
                f"🐌 Slowmode set to **{seconds} seconds**."
            )

    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ I don't have permission to change slowmode.",
            ephemeral=True
        )


# ============================================================
# FUN GAMES
# ============================================================

@bot.tree.command(name="8ball", description="Ask the magic 8-ball")
@app_commands.describe(question="Your question")
async def eight_ball(
    interaction: discord.Interaction,
    question: str
):
    answers = [
        "🎱 Absolutely!",
        "🎱 Yes.",
        "🎱 Definitely.",
        "🎱 Most likely.",
        "🎱 Probably.",
        "🎱 Maybe...",
        "🎱 Ask again later.",
        "🎱 I'm not sure.",
        "🎱 Probably not.",
        "🎱 No.",
        "🎱 Absolutely not!"
    ]

    await interaction.response.send_message(
        f"🎱 **Question:** {question}\n"
        f"**Answer:** {random.choice(answers)}"
    )


@bot.tree.command(name="coinflip", description="Flip a coin")
async def coinflip(interaction: discord.Interaction):
    result = random.choice(["Heads 🪙", "Tails 🪙"])

    await interaction.response.send_message(
        f"🪙 The coin landed on **{result}**!"
    )


@bot.tree.command(name="dice", description="Roll a dice")
@app_commands.describe(sides="Number of sides (2-100)")
async def dice(
    interaction: discord.Interaction,
    sides: app_commands.Range[int, 2, 100] = 6
):
    result = random.randint(1, sides)

    await interaction.response.send_message(
        f"🎲 You rolled **{result}** on a `{sides}`-sided dice!"
    )


@bot.tree.command(name="rps", description="Play Rock Paper Scissors")
@app_commands.describe(choice="Choose rock, paper or scissors")
@app_commands.choices(choice=[
    app_commands.Choice(name="🪨 Rock", value="rock"),
    app_commands.Choice(name="📄 Paper", value="paper"),
    app_commands.Choice(name="✂️ Scissors", value="scissors"),
])
async def rps(
    interaction: discord.Interaction,
    choice: app_commands.Choice[str]
):
    user_choice = choice.value
    bot_choice = random.choice(["rock", "paper", "scissors"])

    emojis = {
        "rock": "🪨",
        "paper": "📄",
        "scissors": "✂️"
    }

    if user_choice == bot_choice:
        result = "🤝 It's a **draw**!"

    elif (
        (user_choice == "rock" and bot_choice == "scissors")
        or
        (user_choice == "paper" and bot_choice == "rock")
        or
        (user_choice == "scissors" and bot_choice == "paper")
    ):
        result = "🎉 **You win!**"

    else:
        result = "😂 **I win!**"

    await interaction.response.send_message(
        f"You: {emojis[user_choice]} **{user_choice.title()}**\n"
        f"Me: {emojis[bot_choice]} **{bot_choice.title()}**\n\n"
        f"{result}"
    )


@bot.tree.command(name="slots", description="Play the slot machine")
async def slots(interaction: discord.Interaction):
    symbols = ["🍒", "🍋", "🍉", "⭐", "💎", "7️⃣"]

    result = [
        random.choice(symbols),
        random.choice(symbols),
        random.choice(symbols)
    ]

    if result[0] == result[1] == result[2]:
        message = "🎉 **JACKPOT! YOU WON!** 💰"
    elif result[0] == result[1] or result[1] == result[2] or result[0] == result[2]:
        message = "🔥 **Two matching! Nice!**"
    else:
        message = "💀 **No match. Better luck next time!**"

    await interaction.response.send_message(
        f"🎰 **{result[0]} | {result[1]} | {result[2]}**\n\n{message}"
    )


@bot.tree.command(name="ship", description="Calculate the love compatibility")
@app_commands.describe(
    user1="First person",
    user2="Second person"
)
async def ship(
    interaction: discord.Interaction,
    user1: discord.Member,
    user2: discord.Member
):
    random.seed(
        min(user1.id, user2.id) + max(user1.id, user2.id)
    )

    percentage = random.randint(0, 100)

    random.seed()

    if percentage >= 90:
        message = "💍 PERFECT MATCH!"
    elif percentage >= 70:
        message = "❤️ Very strong!"
    elif percentage >= 50:
        message = "💕 There might be something!"
    elif percentage >= 30:
        message = "😅 Maybe just friends..."
    else:
        message = "💀 Bro, it's over."

    await interaction.response.send_message(
        f"💘 **{user1.display_name} + {user2.display_name}**\n"
        f"❤️ Compatibility: **{percentage}%**\n"
        f"{message}"
    )


@bot.tree.command(name="roast", description="Get a friendly roast")
@app_commands.describe(member="Member to roast")
async def roast(
    interaction: discord.Interaction,
    member: discord.Member | None = None
):
    member = member or interaction.user

    roasts = [
        "Your Wi-Fi has more personality than you. 💀",
        "Even Google couldn't find your motivation. 😭",
        "Bro's loading... please wait. 🗿",
        "You're not slow, you're just permanently buffering. 😂",
        "Your NPC energy is unmatched. 🤖",
        "Even the tutorial gave up on you. 💀",
        "Bro has 1% battery and 0% brain cells. 😭"
    ]

    await interaction.response.send_message(
        f"🔥 {member.mention} {random.choice(roasts)}"
    )


@bot.tree.command(name="compliment", description="Give someone a compliment")
@app_commands.describe(member="Member to compliment")
async def compliment(
    interaction: discord.Interaction,
    member: discord.Member | None = None
):
    member = member or interaction.user

    compliments = [
        "You're actually awesome. 🔥",
        "You make the server better just by being here. ❤️",
        "Your vibe is immaculate. ✨",
        "You're a legend fr. 👑",
        "You've got main-character energy. 😎",
        "You're more useful than a 100% charged phone. 🔋",
        "Certified W human. 🗿"
    ]

    await interaction.response.send_message(
        f"✨ {member.mention} {random.choice(compliments)}"
    )


@bot.tree.command(name="guess", description="Guess a number from 1 to 10")
@app_commands.describe(number="Your guess")
async def guess(
    interaction: discord.Interaction,
    number: app_commands.Range[int, 1, 10]
):
    answer = random.randint(1, 10)

    if number == answer:
        result = "🎉 **Correct! You got it!**"
    else:
        result = f"❌ Nope! The number was **{answer}**."

    await interaction.response.send_message(
        f"🔢 You guessed **{number}**.\n{result}"
)
if __name__ == "__main__":
    keep_alive()
    bot.run(TOKEN)                                                
