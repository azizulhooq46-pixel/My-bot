import discord
from discord.ext import commands
from datetime import timedelta
import os
from threading import Thread
from flask import Flask

import asyncio
import aiohttp
from discord.ext import tasks

import re
import time
import random

from collections import defaultdict




try:
    from google import genai
except ImportError:
    genai = None

# Add your Render app URL here

	  
app = Flask('')


@app.route('/')
def home():
  return 'Bot is online!'

def run():
  port = int(os.environ.get('PORT', 8080))
  app.run(host='0.0.0.0', port=port)
	


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
@tasks.loop(minutes=10)
async def keep_app_awake():
  url = "https://my-bot-1-mntj.onrender.com/"
  try:
    async with aiohttp.ClientSession() as session:
      async with session.get(url) as response:
        print(f"Self-ping status: {response.status}")
  except Exception as e:
    print(f"Self-ping failed: {e}")


@gogagaga.event
async def on_ready():
  print(f"Logged in as {gogagaga.user}")
  if not keep_app_awake.is_running():
    keep_app_awake.start()
# ping Command
@gogagaga.command()
@commands.cooldown(1, 5, commands.BucketType.user)
async def ping(ctx):
    latency = round(gogagaga.latency * 1000)
    embed = discord.Embed(
        title="🏓 Pong!",
        description=f"Latency is `{latency}ms`",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed)

	
# Warn Command

# ==========================================
# 1. DELETE BUTTON VIEW CLASS
# ==========================================
class ClearWarnView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=None)
        self.user_id = user_id

    @discord.ui.button(emoji="🗑️", style=discord.ButtonStyle.danger)
    async def delete_warn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # কেবল মডারেটর/এডমিনরা বাটন ব্যবহার করতে পারবে
        if not interaction.user.guild_permissions.kick_members:
            await interaction.response.send_message("❌ You don't have permission to clear warnings!", ephemeral=True)
            return

        if self.user_id in warnings_data and warnings_data[self.user_id]:
            warnings_data[self.user_id].clear()
            button.disabled = True
            await interaction.response.edit_message(content="🗑️ **Warnings have been cleared for this user.**", embed=None, view=self)
        else:
            await interaction.response.send_message("No warnings found to clear.", ephemeral=True)


# ==========================================
# 2. WARN COMMAND
# ==========================================
@gogagaga.command()
@commands.has_permissions(kick_members=True)
async def warn(ctx, member: discord.Member, *, reason="No reason provided"):
    user_id = member.id
    
    if user_id not in warnings_data:
        warnings_data[user_id] = []
    warnings_data[user_id].append(reason)

    embed = discord.Embed(
        title="Warning",
        description=f"*{member} has been warned.* | {reason}",
        color=discord.Color.green()
    )

    dm_embed = discord.Embed(
        title=f"**WARNING FROM {ctx.guild.name}**",
        description=f"You have been warned in {ctx.guild.name} for {reason}",
        color=discord.Color.green()
    )

    try:
        await member.send(embed=dm_embed)
    except discord.Forbidden:
        pass

    await ctx.send(embed=embed)


@warn.error
async def warn_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command!")


# ==========================================
# 3. WARNINGS LIST COMMAND
# ==========================================
@gogagaga.command()
async def warnings(ctx, member: discord.Member = None):
    member = member or ctx.author
    user_id = member.id

    user_warns = warnings_data.get(user_id, [])

    if not user_warns:
        embed = discord.Embed(
            title="Warnings",
            description=f"**{member.display_name}** has no warnings.",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)
        return

    warn_text = ""
    for i, reason in enumerate(user_warns, 1):
        warn_text += f"**{i}. Reason:** {reason}\n"

    embed = discord.Embed(
        title=f"Warnings for {member.display_name} ({member.id})",
        description=warn_text,
        color=discord.Color.red()
    )
    embed.set_footer(text=f"Total Warnings: {len(user_warns)}")

    view = ClearWarnView(user_id=user_id)
    await ctx.send(embed=embed, view=view)
			   

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
@mute.error
async def mute_error(ctx, error):
  if isinstance(error, commands.MissingPermissions):
    await ctx.send("❌ You don't have permission to use this command!")
	  
@gogagaga.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="No reason provided"):
    # ১. ইউজারের DM-এর জন্য এমবেড
    dm_embed = discord.Embed(
        title=f"**BANNED FROM {ctx.guild.name}**",
        description=f"You have been banned from {ctx.guild.name} | Reason: {reason}",
        color=discord.Color.red()
    )

    # ২. ব্যান করার আগেই DM পাঠানোর চেষ্টা করা
    try:
        await member.send(embed=dm_embed)
    except discord.Forbidden:
        pass

    # ৩. আসল ব্যান প্রসেস ও চ্যানেলে মেসেজ পাঠানো
    try:
        await member.ban(reason=reason)

        embed = discord.Embed(
            title="Banned",
            description=f"*{member} was banned from {ctx.guild.name}.* | {reason}",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)

    except discord.Forbidden:
        fembed = discord.Embed(
            title="ERROR",
            description="Couldn't ban member since he is higher than me or I lack permission.",
            color=discord.Color.red()
        )
        await ctx.send(embed=fembed)
# Unban Command
@gogagaga.command()
@commands.has_permissions(ban_members=True)
async def unban(ctx, *, user_input: str):
    # ব্যান করা ইউজারদের তালিকা নিয়ে আসা
    banned_users = [entry async for entry in ctx.guild.bans()]
    
    user_to_unban = None

    for ban_entry in banned_users:
        user = ban_entry.user
        # ইউজারনেম, প্রদর্শন নাম বা ID মিলিয়ে দেখা
        if (
            user.name == user_input
            or str(user.id) == user_input
            or f"{user.name}#{user.discriminator}" == user_input
        ):
            user_to_unban = user
            break

    if user_to_unban is None:
        embed = discord.Embed(
            title="Error",
            description=f"Could not find a banned user matching `{user_input}`.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    try:
        await ctx.guild.unban(user_to_unban)
        embed = discord.Embed(
            title="Unbanned",
            description=f"*{user_to_unban.name} has been unbanned.*",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)
    except discord.Forbidden:
        embed = discord.Embed(
            title="Error",
            description="I lack permissions to unban this user.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)


# Role Command (Add or Remove Role)
@gogagaga.command()
@commands.has_permissions(manage_roles=True)
async def role(ctx, member: discord.Member, *, role: discord.Role):
    # ইউজারের যদি আগে থেকেই রোলটি থাকে তবে সরিয়ে দেবে, না থাকলে যোগ করবে
    if role in member.roles:
        await member.remove_roles(role)
        embed = discord.Embed(
            title="Role Removed",
            description=f"Removed **{role.name}** from {member.mention}",
            color=discord.Color.orange()
        )
    else:
        await member.add_roles(role)
        embed = discord.Embed(
            title="Role Added",
            description=f"Added **{role.name}** to {member.mention}",
            color=discord.Color.green()
        )
    await ctx.send(embed=embed)


# Whois Command (User Info & Roles Check)
@gogagaga.command(aliases=["userinfo"])
async def whois(ctx, member: discord.Member = None):
    # ইউজার উল্লেখ না করলে কমান্ড দেওয়া ব্যক্তির তথ্য দেখাবে
    member = member or ctx.author

    # ইউজারের রোলগুলোর তালিকা ( @everyone রোল বাদে )
    roles = [role.mention for role in member.roles if role != ctx.guild.default_role]
    roles_str = ", ".join(roles) if roles else "No Roles"

    embed = discord.Embed(
        title=f"User Info - {member.name}",
        color=member.color
    )
    
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Joined Server", value=member.joined_at.strftime("%b %d, %Y"), inline=True)
    embed.add_field(name="Account Created", value=member.created_at.strftime("%b %d, %Y"), inline=True)
    embed.add_field(name=f"Roles [{len(roles)}]", value=roles_str, inline=False)
    embed.set_footer(text=f"ID: {member.id}")

    await ctx.send(embed=embed)

# Load Google API Key from Render Environment Variable (or replace with os.get

# ==========================================
# GEMINI AI SETUP
# ==========================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(
    api_key=GEMINI_API_KEY
)

AI_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
]
@gogagaga.event
async def on_message(message):

    # Ignore messages sent by the bot itself
    if message.author == gogagaga.user:
        return

    # CHECK IF BOT WAS MENTIONED
    if gogagaga.user in message.mentions:

        # Remove the bot mention
        user_prompt = (
            message.content
            .replace(f"<@{gogagaga.user.id}>", "")
            .replace(f"<@!{gogagaga.user.id}>", "")
            .strip()
        )

        # USER ONLY MENTIONED THE BOT
        if not user_prompt:
            embed = discord.Embed(
                title="👋 Hello!",
                description=(
                    f"How can I help you today, "
                    f"{message.author.mention}?"
                ),
                color=discord.Color.blue()
            )
            await message.reply(embed=embed)
            return

        # GEMINI REQUEST
        async with message.channel.typing():
            try:
                print(f"Gemini request: {message.author} - {user_prompt}")

                response = None
                last_error = None
                used_model = None

                for model_name in AI_MODELS:
                    try:
                        print(f"Trying model: {model_name}")
                        response = client.models.generate_content(
                            model=model_name,
                            contents=user_prompt
                        )
                        used_model = model_name
                        print(f"Model worked: {model_name}")
                        break
                    except Exception as model_error:
                        error_text = str(model_error).lower()
                        last_error = model_error
                        print(f"Model failed: {model_name} -> {model_error}")

                        if (
                            "503" in error_text
                            or "unavailable" in error_text
                            or "high demand" in error_text
                            or "overloaded" in error_text
                            or "resource exhausted" in error_text
                            or "429" in error_text
                        ):
                            continue
                        else:
                            raise model_error

                if response is None:
                    raise last_error

                # CHECK GEMINI RESPONSE
                if response and response.text:
                    ai_text = response.text.strip()

                    if len(ai_text) > 4000:
                        ai_text = ai_text[:3997] + "..."

                    embed = discord.Embed(
                        title="✨ Gemini AI Response",
                        description=ai_text,
                        color=discord.Color.green()
                    )

                    footer_text = f"Requested by {message.author.display_name} | {used_model}"

                    if message.author.avatar:
                        embed.set_footer(
                            text=footer_text,
                            icon_url=message.author.avatar.url
                        )
                    else:
                        embed.set_footer(text=footer_text)

                    await message.reply(embed=embed)
                    print("Gemini response sent!")

                else:
                    embed = discord.Embed(
                        title="⚠️ No Output",
                        description="Gemini didn't return a response.",
                        color=discord.Color.gold()
                    )
                    await message.reply(embed=embed)

            except Exception as e:
                print("================================")
                print("GEMINI API ERROR")
                print(f"Error type: {type(e).__name__}")
                print(f"Error: {e}")
                print("================================")

                error_text = str(e)

                if not error_text:
                    error_text = "Unknown Gemini API error."

                if len(error_text) > 3800:
                    error_text = error_text[:3800] + "..."

                embed = discord.Embed(
                    title="❌ Gemini API Error",
                    description=(
                        "Gemini couldn't process your request.\n\n"
                        f"```{error_text}```"
                    ),
                    color=discord.Color.red()
                )
                await message.reply(embed=embed)
                return

    # NORMAL PREFIX COMMANDS
    await gogagaga.process_commands(message)     
"""
Friendly Discord chat bot
- Waves when a new member joins
- Can chat without being mentioned
- Replies in short, human-like messages
- Uses Gemini with model fallback (same idea as your current bot)

Required Discord Developer Portal intents:
  - MESSAGE CONTENT INTENT
  - SERVER MEMBERS INTENT
  - Presence is not required

Environment variables:
  DISCORD_TOKEN     = your bot token
  GEMINI_API_KEY    = your Gemini API key
  WELCOME_CHANNEL_ID = optional channel id for join waves
  CHAT_CHANNEL_IDS   = optional comma-separated channel ids
                       If empty, the bot can chat in any text channel.
"""




# =========================
# CONFIG
# =========================
COMMAND_PREFIX = "!"

# If set, join waves go here. If empty, the bot uses the server system channel.
WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID", "0") or 0)

# Comma-separated channel IDs where the bot may chat without a mention.
# Leave empty to allow all normal text channels.
_raw_chat_channels = os.getenv("CHAT_CHANNEL_IDS", "").strip()
CHAT_CHANNEL_IDS = {
    int(x.strip()) for x in _raw_chat_channels.split(",") if x.strip().isdigit()
}

# How often the bot is allowed to talk
USER_COOLDOWN_SECONDS = 8
CHANNEL_COOLDOWN_SECONDS = 4
MAX_REPLY_CHARS = 220

# Chance the bot stays quiet on a random message (feels more human)
SKIP_CHANCE = 0.18

AI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
]

SYSTEM_STYLE = """
You are a friendly Discord server member, not a formal assistant.
Talk like a real person in a casual chat.

Rules:
- Keep replies very short: 1 or 2 sentences, usually under 25 words.
- Sound natural. Use simple words.
- You can wave, say hey, ask a small question, or react to what they said.
- Do not use markdown, titles, bullet lists, or long explanations.
- Do not say you are an AI unless asked.
- Stay kind, helpful, and family-friendly.
- No adult content, no insults, no private info requests.
- If someone just said hi, greet them back briefly.
- If you are welcoming a new member, be warm and short.
""".strip()


# =========================
# BOT SETUP
# =========================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents, help_command=None)

# channel_id -> True/False. Default: chat is ON
chat_enabled = defaultdict(lambda: True)
last_user_reply = {}      # user_id -> timestamp
last_channel_reply = {}   # channel_id -> timestamp
recent_joins = {}         # user_id -> timestamp, so the bot can keep chatting a bit after join

client = None
if genai is not None and os.getenv("GEMINI_API_KEY"):
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


# =========================
# HELPERS
# =========================
def clean_mention(text: str, user_id: int) -> str:
    text = text.replace(f"<@{user_id}>", "")
    text = text.replace(f"<@!{user_id}>", "")
    return re.sub(r"\s+", " ", text).strip()


def looks_like_command(content: str) -> bool:
    return content.startswith(COMMAND_PREFIX)


def allowed_chat_channel(channel: discord.abc.Messageable) -> bool:
    if not isinstance(channel, discord.TextChannel):
        return False
    if CHAT_CHANNEL_IDS:
        return channel.id in CHAT_CHANNEL_IDS
    return True


def on_cooldown(user_id: int, channel_id: int) -> bool:
    now = time.time()
    if now - last_user_reply.get(user_id, 0) < USER_COOLDOWN_SECONDS:
        return True
    if now - last_channel_reply.get(channel_id, 0) < CHANNEL_COOLDOWN_SECONDS:
        return True
    return False


def mark_replied(user_id: int, channel_id: int) -> None:
    now = time.time()
    last_user_reply[user_id] = now
    last_channel_reply[channel_id] = now


def should_talk(message: discord.Message, mentioned: bool) -> bool:
    content = message.content.strip()

    if mentioned:
        return True

    # Keep chatting a little after someone just joined
    if message.author.id in recent_joins and time.time() - recent_joins[message.author.id] < 15 * 60:
        return True

    # Greetings and direct-ish chat
    lowered = content.lower()
    greetings = (
        "hi", "hey", "hello", "yo", "sup", "hola", "good morning",
        "good night", "gm", "gn", "whats up", "what's up", "how are you",
        "wyd", "anyone here", "is anyone",
    )
    if any(lowered == g or lowered.startswith(g + " ") or lowered.startswith(g + ",") for g in greetings):
        return True

    # Ignore super short noise like "ok", "k", emojis-only unless mentioned
    if len(content) < 3:
        return False

    # Sometimes stay quiet so it does not reply to every single message
    if random.random() < SKIP_CHANCE:
        return False

    # Skip obvious off-topic spammy stuff
    if content.startswith("http") or content.count("\n") > 6:
        return False

    return True


async def ask_gemini(prompt: str, extra_context: str = "") -> str:
    if client is None:
        return "Heyy, I'm here. My AI key is not set yet though."

    full_prompt = (
        SYSTEM_STYLE
        + "\n\n"
        + (extra_context + "\n\n" if extra_context else "")
        + "User message:\n"
        + prompt
        + "\n\nYour short reply:"
    )

    last_error = None
    for model_name in AI_MODELS:
        try:
            print(f"Trying model: {model_name}")
            response = client.models.generate_content(
                model=model_name,
                contents=full_prompt,
            )
            text = (getattr(response, "text", None) or "").strip()
            if text:
                print(f"Model worked: {model_name}")
                return text[:MAX_REPLY_CHARS]
        except Exception as model_error:
            last_error = model_error
            error_text = str(model_error).lower()
            print(f"Model failed: {model_name} -> {model_error}")
            retryable = any(
                word in error_text
                for word in ("503", "429", "unavailable", "high demand", "overloaded", "resource exhausted")
            )
            if retryable:
                continue
            break

    print(f"Gemini error: {last_error}")
    return "hey, my brain lagged a sec. say that again?"


async def send_human_like(channel: discord.abc.Messageable, text: str, mention: discord.Member | None = None):
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return

    # Keep it short and casual
    if len(text) > MAX_REPLY_CHARS:
        text = text[: MAX_REPLY_CHARS - 3].rsplit(" ", 1)[0] + "..."

    async with channel.typing():
        await asyncio.sleep(random.uniform(0.7, 1.8))
        if mention is not None:
            await channel.send(f"{mention.mention} {text}")
        else:
            await channel.send(text)


def welcome_channel_for(member: discord.Member) -> discord.TextChannel | None:
    guild = member.guild
    if WELCOME_CHANNEL_ID:
        channel = guild.get_channel(WELCOME_CHANNEL_ID)
        if isinstance(channel, discord.TextChannel):
            return channel
    if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
        return guild.system_channel
    for channel in guild.text_channels:
        if channel.permissions_for(guild.me).send_messages:
            return channel
    return None


# =========================
# EVENTS
# =========================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    print("Chat-without-mention is enabled in allowed channels.")
    await bot.change_presence(activity=discord.Game(name="chatting around"))


@bot.event
async def on_member_join(member: discord.Member):
    if member.bot:
        return

    recent_joins[member.id] = time.time()
    channel = welcome_channel_for(member)
    if channel is None:
        return

    waves = [
        f"heyyy {member.mention} 👋 welcome in",
        f"yo {member.mention} welcome 👋",
        f"waveee {member.mention} glad you joined",
        f"hey {member.mention} 👋 make yourself at home",
        f"{member.mention} welcomeee 👋",
    ]
    await send_human_like(channel, random.choice(waves).replace(member.mention, "").strip(), mention=member)

    # Small follow-up, like a person would
    await asyncio.sleep(random.uniform(1.2, 2.5))
    followups = [
        "how did you find this server?",
        "what do you usually hang out for?",
        "hope you like it here :)",
        "say hi if you want, i don't bite",
    ]
    await send_human_like(channel, random.choice(followups))


@bot.event
async def on_message(message: discord.Message):
    # Always let prefix commands work
    await bot.process_commands(message)

    if message.author.bot:
        return
    if message.author == bot.user:
        return
    if not message.guild:
        return
    if looks_like_command(message.content):
        return
    if not allowed_chat_channel(message.channel):
        return
    if not chat_enabled[message.channel.id]:
        return

    mentioned = bot.user in message.mentions
    content = clean_mention(message.content, bot.user.id) if mentioned else message.content.strip()

    if mentioned and not content:
        await send_human_like(message.channel, random.choice(["heyy", "yo what's up", "yeah?", "i'm here"]), mention=message.author)
        return

    if not content:
        return

    if not should_talk(message, mentioned):
        return

    if on_cooldown(message.author.id, message.channel.id):
        return

    mark_replied(message.author.id, message.channel.id)

    extra = f"You are talking to {message.author.display_name} in a Discord server named {message.guild.name}."
    if message.author.id in recent_joins:
        extra += " This person just joined recently, so be extra welcoming and casual."

    reply = await ask_gemini(content, extra_context=extra)
    await send_human_like(message.channel, reply)


# =========================
# COMMANDS
# =========================
@bot.command(name="chat")
@commands.has_permissions(manage_channels=True)
async def chat_toggle(ctx: commands.Context, mode: str = ""):
    """Turn auto chat on or off in this channel. Usage: !chat on  /  !chat off"""
    mode = mode.lower().strip()
    if mode not in {"on", "off"}:
        state = "on" if chat_enabled[ctx.channel.id] else "off"
        await ctx.send(f"auto chat is **{state}** here. use `!chat on` or `!chat off`")
        return

    chat_enabled[ctx.channel.id] = mode == "on"
    await ctx.send(f"okay, auto chat is **{mode}** in this channel")


@bot.command(name="wave")
async def wave_cmd(ctx: commands.Context, member: discord.Member | None = None):
    """Wave at someone. Usage: !wave @user"""
    member = member or ctx.author
    await send_human_like(ctx.channel, random.choice(["heyyy 👋", "waveee 👋", "yo 👋"]), mention=member)


@bot.command(name="ping")
async def ping_cmd(ctx: commands.Context):
    await ctx.send(f"pong `{round(bot.latency * 1000)}ms`")


@chat_toggle.error
async def chat_toggle_error(ctx: commands.Context, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("you need manage channels permission for that")
    else:
        await ctx.send("that command didn't work")


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN") or os.getenv("YOUR_TOKEN_HERE")
    if not token:
        raise SystemExit("Set DISCORD_TOKEN in your environment first.")
    


    keep_alive()
    gogagaga.run(token)
