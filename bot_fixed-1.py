import os, re, random, asyncio, sqlite3, time
from datetime import datetime, timezone
from threading import Thread
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks
from flask import Flask, send_from_directory
try:
    from google import genai
except ImportError:
    genai = None

# ============================================================
# OMNI CAVE - MERGED FIXED VERSION
# Prefix + Slash | Gemini | Welcome/Goodbye | Leveling |
# Reaction Roles | Moderation | Warnings | Fun | Birthday | QOTD
# ============================================================
TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("TOKEN") or os.getenv("YOUR_TOKEN_HERE")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
NEW_MEMBER_AI_CHAT = os.getenv("NEW_MEMBER_AI_CHAT", "true").lower() in ("1", "true", "yes", "on")
NEW_MEMBER_CHAT_MINUTES = int(os.getenv("NEW_MEMBER_CHAT_MINUTES", "15") or 15)
NEW_MEMBER_CHAT_COOLDOWN = int(os.getenv("NEW_MEMBER_CHAT_COOLDOWN", "20") or 20)
NEW_MEMBER_CHAT_MAX_REPLIES = int(os.getenv("NEW_MEMBER_CHAT_MAX_REPLIES", "8") or 8)
DEFAULT_PREFIX = os.getenv("PREFIX", "!")
DEV_GUILD_ID = int(os.getenv("DEV_GUILD_ID", "0") or 0)

if not TOKEN:
    raise RuntimeError("Set DISCORD_TOKEN in Render Environment Variables.")

# ---------------- Render health server ----------------
app = Flask(__name__)


@app.get("/")
def home():
    return send_from_directory(".", "index.html")
@app.get("/health")
def health():
    return {"status": "online", "bot": "Omni Cave"}

def run_web():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")), debug=False, use_reloader=False)

def keep_alive():
    Thread(target=run_web, daemon=True).start()

# ---------------- Database ----------------
DB_FILE = os.getenv("DATABASE_PATH", "omni_cave.db")
db = sqlite3.connect(DB_FILE, check_same_thread=False)
db.row_factory = sqlite3.Row

def init_db():
    with db:
        db.execute("""CREATE TABLE IF NOT EXISTS settings (
            guild_id INTEGER PRIMARY KEY,
            prefix TEXT NOT NULL DEFAULT '!',
            welcome_channel INTEGER DEFAULT 0,
            welcome_text TEXT DEFAULT 'Hey {mention}! Welcome to **{server}**! 🎉',
            welcome_embed INTEGER DEFAULT 1,
            goodbye_channel INTEGER DEFAULT 0,
            goodbye_text TEXT DEFAULT '**{name}** has left **{server}**. Goodbye! 👋',
            goodbye_embed INTEGER DEFAULT 1,
            level_channel INTEGER DEFAULT 0,
            level_text TEXT DEFAULT '🎉 {mention} reached **Level {level}**!',
            level_embed INTEGER DEFAULT 0,
            leveling_enabled INTEGER DEFAULT 1,
            qotd_channel INTEGER DEFAULT 0
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS levels (
            guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            xp INTEGER NOT NULL DEFAULT 0, level INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id,user_id)
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS xp_cooldowns (
            guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, last_time REAL NOT NULL,
            PRIMARY KEY (guild_id,user_id)
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS warnings (
            guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            reason TEXT NOT NULL, moderator_id INTEGER NOT NULL, created_at TEXT NOT NULL
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS reaction_roles (
            guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL, emoji TEXT NOT NULL, role_id INTEGER NOT NULL,
            PRIMARY KEY(guild_id,message_id,emoji)
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS birthdays (
            guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            month INTEGER NOT NULL, day INTEGER NOT NULL,
            PRIMARY KEY(guild_id,user_id)
        )""")
init_db()

def ensure_guild(gid):
    with db:
        db.execute("INSERT OR IGNORE INTO settings(guild_id,prefix) VALUES(?,?)", (gid, DEFAULT_PREFIX))

def settings(gid):
    ensure_guild(gid)
    return db.execute("SELECT * FROM settings WHERE guild_id=?", (gid,)).fetchone()

def set_setting(gid, key, value):
    allowed = {"prefix","welcome_channel","welcome_text","welcome_embed","goodbye_channel","goodbye_text","goodbye_embed","level_channel","level_text","level_embed","leveling_enabled","qotd_channel"}
    if key not in allowed: raise ValueError("Invalid setting")
    ensure_guild(gid)
    with db: db.execute(f"UPDATE settings SET {key}=? WHERE guild_id=?", (value,gid))

def render_text(template, member, level=None):
    values = {
        "mention": member.mention,
        "name": discord.utils.escape_markdown(member.display_name),
        "username": discord.utils.escape_markdown(member.name),
        "server": discord.utils.escape_markdown(member.guild.name),
        "member_count": str(member.guild.member_count or 0),
        "level": str(level if level is not None else "")
    }
    try: return template.format(**values)
    except (KeyError,ValueError,IndexError): return template

async def send_configured(channel_id, text, use_embed, title, member, level=None):
    if not channel_id: return
    channel = member.guild.get_channel(int(channel_id))
    if not channel or not hasattr(channel,"send"): return
    content = render_text(text, member, level)
    try:
        if use_embed:
            e = discord.Embed(title=title, description=content, color=discord.Color.blurple())
            e.set_thumbnail(url=member.display_avatar.url)
            await channel.send(embed=e)
        else:
            await channel.send(content)
    except (discord.Forbidden,discord.HTTPException): pass

# ---------------- Bot ----------------
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True
intents.reactions = True

async def dynamic_prefix(bot, message):
    return settings(message.guild.id)["prefix"] if message.guild else DEFAULT_PREFIX

class OmniCave(commands.Bot):
    async def setup_hook(self):
        try:
            if DEV_GUILD_ID:
                g = discord.Object(id=DEV_GUILD_ID)
                self.tree.copy_global_to(guild=g)
                synced = await self.tree.sync(guild=g)
                print(f"Synced {len(synced)} commands to DEV_GUILD_ID.")
            else:
                synced = await self.tree.sync()
                print(f"Synced {len(synced)} global commands.")
        except Exception as e: print("Slash sync error:", e)

bot = OmniCave(command_prefix=dynamic_prefix, intents=intents, help_command=None, case_insensitive=True)

# ---------------- Gemini ----------------
gemini = None
if genai and GEMINI_API_KEY:
    try: gemini = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e: print("Gemini init error:", e)

GEMINI_MODELS = [
    "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash",
    "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash"
]

# New-member AI conversation sessions: (guild_id, user_id) -> session data
new_member_sessions = {}

def start_new_member_session(guild_id, user_id):
    now = time.time()
    new_member_sessions[(guild_id, user_id)] = {
        "until": now + max(1, NEW_MEMBER_CHAT_MINUTES) * 60,
        "last_reply": 0.0,
        "replies": 0,
    }

def get_new_member_session(guild_id, user_id):
    session = new_member_sessions.get((guild_id, user_id))
    if not session:
        return None
    now = time.time()
    if now >= session["until"] or session["replies"] >= NEW_MEMBER_CHAT_MAX_REPLIES:
        new_member_sessions.pop((guild_id, user_id), None)
        return None
    return session

SYSTEM_STYLE = """You are Omni Cave, a friendly Discord community bot. Be casual, helpful, family-friendly and concise. Usually answer in 1-4 short sentences unless the user asks for detail. Never claim to be human and never ask for private information."""

async def ask_ai(prompt, extra_context=""):
    if gemini is None:
        if genai is None: return "AI setup error: install `google-genai` in requirements.txt."
        if not GEMINI_API_KEY: return "AI configuration error: `GEMINI_API_KEY` is missing in Render Environment Variables."
        return "AI client could not start. Check the Render logs."
    full = f"{SYSTEM_STYLE}\n\n{extra_context}\n\nUser:\n{prompt}"
    errors=[]
    for model in GEMINI_MODELS:
        try:
            response = await asyncio.to_thread(gemini.models.generate_content, model=model, contents=full)
            text = (getattr(response,"text",None) or "").strip()
            if text: return text[:3900]
            errors.append(f"{model}: empty response")
        except Exception as e:
            errors.append(f"{model}: {type(e).__name__}: {e}")
    return "Omni Cave AI Error\n\nAll configured Gemini models failed.\n```text\n" + "\n".join(errors)[:3000] + "\n```"

# ---------------- Helpers ----------------
def xp_needed(level): return 100 + level * 50

def add_xp(gid, uid, amount):
    row=db.execute("SELECT xp,level FROM levels WHERE guild_id=? AND user_id=?",(gid,uid)).fetchone()
    xp,level=(row["xp"],row["level"]) if row else (0,0)
    xp += amount; old=level
    while xp >= xp_needed(level): xp -= xp_needed(level); level += 1
    with db:
        db.execute("INSERT INTO levels(guild_id,user_id,xp,level) VALUES(?,?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET xp=excluded.xp,level=excluded.level",(gid,uid,xp,level))
    return xp,level,level>old

def parse_bool(v):
    v=str(v).lower().strip()
    if v in ("true","yes","on","1","enable","enabled"): return True
    if v in ("false","no","off","0","disable","disabled"): return False
    raise ValueError

def emoji_key(e): return str(e)

def staff_or_admin(member):
    p=member.guild_permissions
    return p.administrator or p.manage_guild or p.manage_roles

# ---------------- Events ----------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="Omni Cave • /help"))

@bot.event
async def on_member_join(member):
    if member.bot: return
    s=settings(member.guild.id)
    channel_id=s["welcome_channel"]
    if not channel_id:
        env=int(os.getenv("WELCOME_CHANNEL_ID","0") or 0); channel_id=env
    if not channel_id and member.guild.system_channel:
        channel_id=member.guild.system_channel.id

    # Normal configurable welcome message still works.
    await send_configured(channel_id,s["welcome_text"],bool(s["welcome_embed"]),"Welcome to Omni Cave!",member)

    # AI NEW-MEMBER MODE: greet the new member, then temporarily chat with them
    # when they send messages, without requiring a mention.
    if NEW_MEMBER_AI_CHAT and channel_id and gemini is not None:
        start_new_member_session(member.guild.id, member.id)
        channel = member.guild.get_channel(int(channel_id))
        if channel is not None and hasattr(channel, "send"):
            context = (
                f"Server: {member.guild.name}\n"
                f"New member: {member.display_name}\n"
                "This person just joined the Discord server. Greet them warmly. "
                "Start with a friendly wave emoji (👋), mention them, introduce yourself as Omni Cave, "
                "and ask one simple question to start a conversation. Keep it short, natural, and family-friendly. "
                "Do not ask for private information."
            )
            try:
                async with channel.typing():
                    greeting = await ask_ai(
                        "Create a short welcome message for this new member.",
                        context,
                    )
                greeting = greeting.strip()
                if not greeting.startswith("👋"):
                    greeting = "👋 " + greeting
                await channel.send(f"{member.mention} {greeting}")
            except (discord.HTTPException, discord.Forbidden):
                # The normal welcome message has already been sent, so AI failure is non-fatal.
                pass

@bot.event
async def on_member_remove(member):
    if member.bot: return
    s=settings(member.guild.id)
    await send_configured(s["goodbye_channel"],s["goodbye_text"],bool(s["goodbye_embed"]),"Goodbye!",member)

@bot.event
async def on_message(message):
    if message.author.bot: return
    if not message.guild:
        await bot.process_commands(message); return

    content=message.content or ""
    prefix=settings(message.guild.id)["prefix"]
    is_prefix_command=content.startswith(prefix)

    # XP never blocks AI. Prefix commands are processed first.
    await bot.process_commands(message)
    if is_prefix_command: return

    s=settings(message.guild.id)
    if s["leveling_enabled"]:
        now=time.time(); row=db.execute("SELECT last_time FROM xp_cooldowns WHERE guild_id=? AND user_id=?",(message.guild.id,message.author.id)).fetchone()
        if row is None or now-row["last_time"]>=60:
            xp,level,up=add_xp(message.guild.id,message.author.id,random.randint(8,15))
            with db:
                db.execute("INSERT INTO xp_cooldowns(guild_id,user_id,last_time) VALUES(?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET last_time=excluded.last_time",(message.guild.id,message.author.id,now))
            if up:
                s=settings(message.guild.id)
                # If no custom level channel is set, announce in the current channel.
                if s["level_channel"]:
                    await send_configured(s["level_channel"],s["level_text"],bool(s["level_embed"]),"Level Up!",message.author,level)
                else:
                    text=render_text(s["level_text"],message.author,level)
                    try:
                        if s["level_embed"]:
                            await message.channel.send(embed=discord.Embed(title="Level Up!",description=text,color=discord.Color.gold()))
                        else: await message.channel.send(text)
                    except discord.HTTPException: pass

    # NEW-MEMBER AI CHAT: for a short time after joining, reply naturally to the
    # new member even when they do not mention the bot. This is rate-limited so
    # Omni Cave does not spam every message.
    new_session = get_new_member_session(message.guild.id, message.author.id) if NEW_MEMBER_AI_CHAT else None
    if new_session:
        now = time.time()
        if now - new_session["last_reply"] >= NEW_MEMBER_CHAT_COOLDOWN:
            mentioned_now = bool(bot.user and bot.user in message.mentions)
            prompt_now = message.content.strip()
            if bot.user:
                prompt_now = prompt_now.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
            if prompt_now:
                context = (
                    f"Server: {message.guild.name}\n"
                    f"User: {message.author.display_name} is a newly joined member.\n"
                    "You are already chatting with this new member. Continue the conversation naturally. "
                    "Be welcoming, casual, family-friendly, and concise. Ask a follow-up question only when it feels natural. "
                    "Never ask for private information. Do not mention this hidden session or its time limit. "
                    f"The user {'mentioned you' if mentioned_now else 'sent a message'}: {prompt_now}"
                )
                async with message.channel.typing():
                    reply = await ask_ai(prompt_now, context)
                e = discord.Embed(title="✨ Omni Cave", description=reply, color=discord.Color.green())
                try:
                    await message.reply(embed=e)
                    new_session["last_reply"] = now
                    new_session["replies"] += 1
                except discord.HTTPException:
                    pass
                return

    mentioned=bool(bot.user and bot.user in message.mentions)
    reply_to_bot=False
    if message.reference and message.reference.message_id:
        try:
            ref=message.reference.resolved
            if ref is None: ref=await message.channel.fetch_message(message.reference.message_id)
            reply_to_bot=bool(bot.user and ref.author.id==bot.user.id)
        except (discord.NotFound,discord.Forbidden,discord.HTTPException): pass

    # FIX: mentions and replies to the bot are AI messages, not commands.
    if mentioned or reply_to_bot:
        prompt=content
        if bot.user:
            prompt=prompt.replace(f"<@{bot.user.id}>","").replace(f"<@!{bot.user.id}>","")
        prompt=prompt.strip()
        if not prompt:
            prompt="Reply to the user naturally and ask what they need."
        context=f"Server: {message.guild.name}\nUser: {message.author.display_name}"
        if reply_to_bot:
            context += "\nThe user is replying to an earlier message from Omni Cave. Continue the conversation naturally."
        async with message.channel.typing(): reply=await ask_ai(prompt,context)
        e=discord.Embed(title="✨ Omni Cave AI",description=reply,color=discord.Color.green())
        e.set_footer(text=f"Requested by {message.author.display_name}")
        try: await message.reply(embed=e)
        except discord.HTTPException: pass
        return

# ---------------- General hybrid commands ----------------
@bot.hybrid_command(name="help",description="Show Omni Cave commands.")
async def help_command(ctx):
    p=settings(ctx.guild.id)["prefix"] if ctx.guild else DEFAULT_PREFIX
    e=discord.Embed(title="🤖 Omni Cave Help",description=f"Prefix: `{p}`\nCommands work with both `{p}command` and `/command`.",color=discord.Color.blurple())
    e.add_field(name="General",value=f"`{p}ping` `serverinfo` `userinfo` `rank` `leaderboard` `ai`",inline=False)
    e.add_field(name="Settings",value=f"`setprefix` `welcomechannel` `welcometext` `welcomeembed` `goodbyechannel` `goodbyetext` `goodbyeembed` `levelchannel` `leveltext` `levelembed` `leveling` `settings`",inline=False)
    e.add_field(name="Moderation",value=f"`warn` `warnings` `clearwarning` `clearwarnings` `mute` `ban` `unban` `kick` `clear` `role` `setnick` `slowmode`",inline=False)
    e.add_field(name="Fun",value=f"`8ball` `coinflip` `dice` `rps` `slots` `ship` `roast` `compliment`",inline=False)
    e.add_field(name="Server",value=f"`setbirthday` `birthday` `setqotd` `qotd` `reactionrole` `removereactionrole`",inline=False)
    await ctx.send(embed=e)

@bot.hybrid_command(name="ping",description="Check bot latency.")
async def ping(ctx): await ctx.send(f"🏓 Pong! `{round(bot.latency*1000)}ms`")

@bot.hybrid_command(name="serverinfo",description="Show server information.")
@commands.guild_only()
async def serverinfo(ctx):
    g=ctx.guild; e=discord.Embed(title=g.name,color=discord.Color.blurple())
    if g.icon: e.set_thumbnail(url=g.icon.url)
    e.add_field(name="Members",value=str(g.member_count or 0)); e.add_field(name="Roles",value=str(len(g.roles))); e.add_field(name="Channels",value=str(len(g.channels)))
    e.add_field(name="Owner",value=f"<@{g.owner_id}>"); e.add_field(name="Created",value=discord.utils.format_dt(g.created_at,"D"))
    await ctx.send(embed=e)

@bot.hybrid_command(name="userinfo",description="Show a member's information.")
@commands.guild_only()
async def userinfo(ctx,member:Optional[discord.Member]=None):
    m=member or ctx.author; e=discord.Embed(title=f"User info: {m}",color=discord.Color.blurple()); e.set_thumbnail(url=m.display_avatar.url)
    e.add_field(name="ID",value=str(m.id)); e.add_field(name="Joined",value=discord.utils.format_dt(m.joined_at,"D") if m.joined_at else "Unknown"); e.add_field(name="Created",value=discord.utils.format_dt(m.created_at,"D")); await ctx.send(embed=e)

@bot.hybrid_command(name="setprefix",description="Change the server prefix.")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def setprefix(ctx,prefix:str):
    if not 1<=len(prefix)<=5 or any(c.isspace() for c in prefix) or prefix.startswith("/"): return await ctx.send("❌ Prefix must be 1-5 characters, have no spaces, and cannot start with `/`.")
    set_setting(ctx.guild.id,"prefix",prefix); await ctx.send(f"✅ Prefix changed to `{prefix}`")

# ---------------- Config commands ----------------
@bot.hybrid_command(name="welcomechannel",description="Set the welcome channel.")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def welcomechannel(ctx,channel:discord.TextChannel): set_setting(ctx.guild.id,"welcome_channel",channel.id); await ctx.send(f"✅ Welcome channel: {channel.mention}")

@bot.hybrid_command(name="welcometext",description="Set welcome message. Use {mention} {name} {username} {server} {member_count}.")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def welcometext(ctx,*,text:str): set_setting(ctx.guild.id,"welcome_text",text); await ctx.send("✅ Welcome message saved.")

@bot.hybrid_command(name="welcomeembed",description="Turn welcome embeds on/off.")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def welcomeembed(ctx,enabled:bool): set_setting(ctx.guild.id,"welcome_embed",int(enabled)); await ctx.send(f"✅ Welcome embeds: {'ON' if enabled else 'OFF'}")

@bot.hybrid_command(name="goodbyechannel",description="Set the goodbye channel.")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def goodbyechannel(ctx,channel:discord.TextChannel): set_setting(ctx.guild.id,"goodbye_channel",channel.id); await ctx.send(f"✅ Goodbye channel: {channel.mention}")

@bot.hybrid_command(name="goodbyetext",description="Set goodbye message.")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def goodbyetext(ctx,*,text:str): set_setting(ctx.guild.id,"goodbye_text",text); await ctx.send("✅ Goodbye message saved.")

@bot.hybrid_command(name="goodbyeembed",description="Turn goodbye embeds on/off.")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def goodbyeembed(ctx,enabled:bool): set_setting(ctx.guild.id,"goodbye_embed",int(enabled)); await ctx.send(f"✅ Goodbye embeds: {'ON' if enabled else 'OFF'}")

@bot.hybrid_command(name="levelchannel",description="Set level-up channel.")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def levelchannel(ctx,channel:discord.TextChannel): set_setting(ctx.guild.id,"level_channel",channel.id); await ctx.send(f"✅ Level-up channel: {channel.mention}")

@bot.hybrid_command(name="leveltext",description="Set level-up message. Use {mention} {name} {server} {level}.")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def leveltext(ctx,*,text:str): set_setting(ctx.guild.id,"level_text",text); await ctx.send("✅ Level-up message saved.")

@bot.hybrid_command(name="levelembed",description="Turn level-up embeds on/off.")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def levelembed(ctx,enabled:bool): set_setting(ctx.guild.id,"level_embed",int(enabled)); await ctx.send(f"✅ Level-up embeds: {'ON' if enabled else 'OFF'}")

@bot.hybrid_command(name="leveling",description="Enable or disable leveling.")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def leveling(ctx,enabled:bool): set_setting(ctx.guild.id,"leveling_enabled",int(enabled)); await ctx.send(f"✅ Leveling: {'ON' if enabled else 'OFF'}")

@bot.hybrid_command(name="settings",description="Show bot settings.")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def settings_cmd(ctx):
    s=settings(ctx.guild.id); ch=lambda x:f"<#{x}>" if x else "Not set"
    e=discord.Embed(title="Omni Cave Settings",color=discord.Color.blurple())
    e.add_field(name="Prefix",value=f"`{s['prefix']}`"); e.add_field(name="Welcome",value=f"{ch(s['welcome_channel'])}\nEmbed: {bool(s['welcome_embed'])}"); e.add_field(name="Goodbye",value=f"{ch(s['goodbye_channel'])}\nEmbed: {bool(s['goodbye_embed'])}"); e.add_field(name="Level",value=f"{ch(s['level_channel'])}\nEmbed: {bool(s['level_embed'])}\nEnabled: {bool(s['leveling_enabled'])}"); await ctx.send(embed=e)

# ---------------- AI ----------------
@bot.hybrid_command(name="ai",description="Ask Omni Cave AI.")
async def ai_command(ctx,*,prompt:str):
    async with ctx.typing(): reply=await ask_ai(prompt,f"Server: {ctx.guild.name if ctx.guild else 'DM'}\nUser: {ctx.author.display_name}")
    await ctx.send(embed=discord.Embed(title="✨ Omni Cave AI",description=reply,color=discord.Color.green()))

# ---------------- Level ----------------
@bot.hybrid_command(name="rank",aliases=["level","xp"],description="Show level and XP.")
@commands.guild_only()
async def rank(ctx,member:Optional[discord.Member]=None):
    m=member or ctx.author; r=db.execute("SELECT xp,level FROM levels WHERE guild_id=? AND user_id=?",(ctx.guild.id,m.id)).fetchone(); xp=r["xp"] if r else 0; lvl=r["level"] if r else 0
    e=discord.Embed(title=f"🏆 {m.display_name}'s Rank",color=discord.Color.gold()); e.set_thumbnail(url=m.display_avatar.url); e.add_field(name="Level",value=str(lvl)); e.add_field(name="XP",value=f"{xp}/{xp_needed(lvl)}"); await ctx.send(embed=e)

@bot.hybrid_command(name="leaderboard",aliases=["lb","top"],description="Show the top 10 members.")
@commands.guild_only()
async def leaderboard(ctx):
    rows=db.execute("SELECT user_id,xp,level FROM levels WHERE guild_id=? ORDER BY level DESC,xp DESC LIMIT 10",(ctx.guild.id,)).fetchall()
    if not rows:return await ctx.send("Nobody has earned XP yet!")
    await ctx.send(embed=discord.Embed(title="🏆 Omni Cave Leaderboard",description="\n".join(f"**{i}.** <@{r['user_id']}> — Level {r['level']} • {r['xp']} XP" for i,r in enumerate(rows,1)),color=discord.Color.gold()))

# ---------------- Moderation / warnings ----------------
@bot.hybrid_command(name="warn",description="Warn a member.")
@commands.guild_only()
@commands.has_guild_permissions(moderate_members=True)
async def warn(ctx,member:discord.Member,*,reason:str):
    with db: db.execute("INSERT INTO warnings VALUES(?,?,?,?,?)",(ctx.guild.id,member.id,reason,ctx.author.id,datetime.now(timezone.utc).isoformat()))
    await ctx.send(f"⚠️ Warned {member.mention}. Reason: {reason}")

@bot.hybrid_command(name="warnings",description="View a member's warnings.")
@commands.guild_only()
@commands.has_guild_permissions(moderate_members=True)
async def warnings(ctx,member:discord.Member):
    rows=db.execute("SELECT rowid,reason,moderator_id,created_at FROM warnings WHERE guild_id=? AND user_id=? ORDER BY rowid",(ctx.guild.id,member.id)).fetchall()
    if not rows:return await ctx.send(f"{member.mention} has no warnings.")
    lines=[]
    for i,r in enumerate(rows,1): lines.append(f"**{i}.** {r['reason']} — <@{r['moderator_id']}> • <t:{int(datetime.fromisoformat(r['created_at']).timestamp())}:R>")
    await ctx.send(embed=discord.Embed(title=f"Warnings for {member}",description="\n".join(lines),color=discord.Color.orange()).set_footer(text="Use /clearwarning <member> <number> to delete one."))

@bot.hybrid_command(name="clearwarning",description="Delete one specific warning by its number.")
@commands.guild_only()
@commands.has_guild_permissions(moderate_members=True)
async def clearwarning(ctx,member:discord.Member,number:int):
    rows=db.execute("SELECT rowid FROM warnings WHERE guild_id=? AND user_id=? ORDER BY rowid",(ctx.guild.id,member.id)).fetchall()
    if number<1 or number>len(rows):return await ctx.send(f"❌ Warning number must be between 1 and {len(rows)}.")
    rowid=rows[number-1]["rowid"]
    with db: db.execute("DELETE FROM warnings WHERE rowid=?",(rowid,))
    await ctx.send(f"🗑️ Deleted warning **#{number}** for {member.mention}.")

@bot.hybrid_command(name="clearwarnings",description="Delete all warnings for a member.")
@commands.guild_only()
@commands.has_guild_permissions(moderate_members=True)
async def clearwarnings(ctx,member:discord.Member):
    with db: cur=db.execute("DELETE FROM warnings WHERE guild_id=? AND user_id=?",(ctx.guild.id,member.id))
    await ctx.send(f"🗑️ Deleted {cur.rowcount} warning(s) for {member.mention}.")


@bot.hybrid_command(
    name="mute",
    description="Timeout a member. Examples: 10m, 10min, 2h, 1d."
)
@commands.guild_only()
@commands.has_guild_permissions(moderate_members=True)
async def mute(
    ctx,
    member: discord.Member,
    duration: str,
    *,
    reason: str = "No reason provided"
):
    # Don't allow bots to be timed out
    if member.bot:
        return await ctx.send("❌ You can't timeout a bot.")

    # Don't allow timing out yourself
    if member.id == ctx.author.id:
        return await ctx.send("❌ You can't timeout yourself.")

    # Don't allow timing out the server owner
    if member.id == ctx.guild.owner_id:
        return await ctx.send("❌ You can't timeout the server owner.")

    # Check role hierarchy
    bot_member = ctx.guild.me

    if bot_member is None:
        return await ctx.send("❌ I couldn't determine my server role.")

    if member.top_role >= bot_member.top_role:
        return await ctx.send(
            "❌ I can't timeout this member because their highest role "
            "is equal to or higher than mine."
        )

    # Accept:
    # 10m, 10min, 10minute, 10minutes
    # 2h, 2hr, 2hour, 2hours
    # 1d, 1day, 1days
    match = re.fullmatch(
        r"(\d+)\s*"
        r"(m|min|minute|minutes|"
        r"h|hr|hour|hours|"
        r"d|day|days)",
        duration.lower().strip()
    )

    if not match:
        return await ctx.send(
            "❌ Invalid duration.\n"
            "Use something like `10m`, `10min`, `2h`, `2hours`, or `1d`."
        )

    amount = int(match.group(1))
    unit = match.group(2)

    # Convert everything to minutes
    if unit in ("m", "min", "minute", "minutes"):
        minutes = amount

    elif unit in ("h", "hr", "hour", "hours"):
        minutes = amount * 60

    else:
        minutes = amount * 1440

    # Discord maximum timeout = 28 days
    if minutes > 40320:
        return await ctx.send(
            "❌ Discord's maximum timeout is **28 days**."
        )

    if minutes <= 0:
        return await ctx.send(
            "❌ The duration must be greater than 0."
        )

    # Apply timeout
    try:
        until = discord.utils.utcnow() + __import__("datetime").timedelta(
            minutes=minutes
        )

        await member.timeout(
            until,
            reason=reason
        )

        await ctx.send(
            f"🔇 Timed out {member.mention} for **{duration}**.\n"
            f"📝 Reason: {reason}"
        )

    except discord.Forbidden:
        await ctx.send(
            "❌ Discord refused the timeout. "
            "Check my **Moderate Members** permission and role position."
        )

    except discord.HTTPException as e:
        await ctx.send(
            f"❌ Discord returned an error while timing out the member: `{e}`"
        )

    except Exception as e:
        print(f"Mute error: {type(e).__name__}: {e}")
        await ctx.send(
            "⚠️ Something unexpected went wrong while timing out the member."
        )

@bot.hybrid_command(name="kick",description="Kick a member.")
@commands.guild_only()
@commands.has_guild_permissions(kick_members=True)
async def kick(ctx,member:discord.Member,*,reason:str="No reason provided"): await member.kick(reason=reason); await ctx.send(f"👢 Kicked {member.mention}. Reason: {reason}")

@bot.hybrid_command(name="ban",description="Ban a member.")
@commands.guild_only()
@commands.has_guild_permissions(ban_members=True)
async def ban(ctx,member:discord.Member,*,reason:str="No reason provided"): await member.ban(reason=reason); await ctx.send(f"🔨 Banned {member.mention}. Reason: {reason}")

@bot.hybrid_command(name="unban",description="Unban by Discord user ID.")
@commands.guild_only()
@commands.has_guild_permissions(ban_members=True)
async def unban(ctx,user_id:str):
    try: user=await bot.fetch_user(int(user_id)); await ctx.guild.unban(user); await ctx.send(f"✅ Unbanned {user}.")
    except (ValueError,discord.NotFound): await ctx.send("❌ Invalid ID or that user is not banned.")

@bot.hybrid_command(name="role",description="Add or remove a role from a member.")
@commands.guild_only()
@commands.has_guild_permissions(manage_roles=True)
async def role(ctx,member:discord.Member,role:discord.Role):
    if role>=ctx.guild.me.top_role:return await ctx.send("❌ My role must be above that role.")
    if role in member.roles: await member.remove_roles(role); await ctx.send(f"➖ Removed {role.mention} from {member.mention}.")
    else: await member.add_roles(role); await ctx.send(f"➕ Added {role.mention} to {member.mention}.")

@bot.hybrid_command(name="setnick",description="Set a member nickname.")
@commands.guild_only()
@commands.has_guild_permissions(manage_nicknames=True)
async def setnick(ctx,member:discord.Member,nickname:str): await member.edit(nick=nickname); await ctx.send(f"✅ Nickname updated for {member.mention}.")

@bot.hybrid_command(name="clear",description="Delete 1-100 messages.")
@commands.guild_only()
@commands.has_guild_permissions(manage_messages=True)
async def clear(ctx,amount:int):
    if not 1<=amount<=100:return await ctx.send("Choose 1-100.")
    deleted=await ctx.channel.purge(limit=amount+(0 if ctx.interaction else 1)); await ctx.send(f"🧹 Deleted {len(deleted)} messages.")

@bot.hybrid_command(name="slowmode",description="Set channel slowmode in seconds.")
@commands.guild_only()
@commands.has_guild_permissions(manage_channels=True)
async def slowmode(ctx,seconds:int):
    if not 0<=seconds<=21600:return await ctx.send("Use 0-21600 seconds.")
    await ctx.channel.edit(slowmode_delay=seconds); await ctx.send(f"🐢 Slowmode set to `{seconds}` seconds.")

# ---------------- Reaction roles ----------------
@bot.hybrid_command(name="reactionrole",description="Configure a reaction role: channel message_id emoji role.")
@commands.guild_only()
@commands.has_guild_permissions(manage_roles=True)
async def reactionrole(ctx,channel:discord.TextChannel,message_id:str,emoji:str,role:discord.Role):
    try: mid=int(message_id); msg=await channel.fetch_message(mid); await msg.add_reaction(emoji)
    except ValueError:return await ctx.send("❌ Message ID must be numeric.")
    except discord.HTTPException:return await ctx.send("❌ I couldn't find/add that emoji. Check my permissions.")
    if role.is_default() or role.managed or role>=ctx.guild.me.top_role:return await ctx.send("❌ That role cannot be assigned by me.")
    with db: db.execute("INSERT OR REPLACE INTO reaction_roles VALUES(?,?,?,?,?)",(ctx.guild.id,channel.id,mid,emoji,role.id))
    await ctx.send(f"✅ Reaction role saved: {emoji} → {role.mention}")

@bot.hybrid_command(name="removereactionrole",description="Remove a reaction role mapping.")
@commands.guild_only()
@commands.has_guild_permissions(manage_roles=True)
async def removereactionrole(ctx,message_id:str,emoji:str):
    try: mid=int(message_id)
    except ValueError:return await ctx.send("❌ Message ID must be numeric.")
    with db: cur=db.execute("DELETE FROM reaction_roles WHERE guild_id=? AND message_id=? AND emoji=?",(ctx.guild.id,mid,emoji))
    await ctx.send("✅ Removed." if cur.rowcount else "❌ Mapping not found.")

@bot.event
async def on_raw_reaction_add(payload):
    if not payload.guild_id or (bot.user and payload.user_id==bot.user.id):return
    r=db.execute("SELECT role_id FROM reaction_roles WHERE guild_id=? AND message_id=? AND emoji=?",(payload.guild_id,payload.message_id,emoji_key(payload.emoji))).fetchone()
    if not r:return
    g=bot.get_guild(payload.guild_id); m=g.get_member(payload.user_id) if g else None; role=g.get_role(r["role_id"]) if g else None
    if m and role and not m.bot:
        try: await m.add_roles(role,reason="Omni Cave reaction role")
        except discord.HTTPException: pass

@bot.event
async def on_raw_reaction_remove(payload):
    if not payload.guild_id:return
    r=db.execute("SELECT role_id FROM reaction_roles WHERE guild_id=? AND message_id=? AND emoji=?",(payload.guild_id,payload.message_id,emoji_key(payload.emoji))).fetchone()
    if not r:return
    g=bot.get_guild(payload.guild_id); m=g.get_member(payload.user_id) if g else None; role=g.get_role(r["role_id"]) if g else None
    if m and role and not m.bot:
        try: await m.remove_roles(role,reason="Omni Cave reaction role removed")
        except discord.HTTPException: pass

# ---------------- Fun ----------------
@bot.hybrid_command(name="8ball",description="Ask the magic 8-ball.")
async def eightball(ctx,*,question:str): await ctx.send(f"🎱 {random.choice(['Yes.','No.','Definitely!','Probably.','Ask again later.','Absolutely not.'])}")

@bot.hybrid_command(name="coinflip",description="Flip a coin.")
async def coinflip(ctx): await ctx.send(f"🪙 **{random.choice(['Heads','Tails'])}**")

@bot.hybrid_command(name="dice",description="Roll a die.")
async def dice(ctx,sides:int=6):
    if not 2<=sides<=1000:return await ctx.send("Sides must be 2-1000.")
    await ctx.send(f"🎲 You rolled **{random.randint(1,sides)}**")

@bot.hybrid_command(name="rps",description="Rock paper scissors.")
async def rps(ctx,choice:str):
    choice=choice.lower(); choices=["rock","paper","scissors"]
    if choice not in choices:return await ctx.send("Choose rock, paper, or scissors.")
    botc=random.choice(choices); result="Tie!" if choice==botc else ("You win! 🎉" if (choice,botc) in [("rock","scissors"),("paper","rock"),("scissors","paper")] else "I win! 😈")
    await ctx.send(f"You: **{choice}** | Me: **{botc}** → **{result}**")

@bot.hybrid_command(name="slots",description="Spin the slots.")
async def slots(ctx):
    a=[random.choice("🍒🍋🍊🍇⭐7️⃣") for _ in range(3)]; await ctx.send("🎰 | " + " | ".join(a) + " |\n" + ("🎉 **JACKPOT!**" if len(set(a))==1 else "Try again!"))

@bot.hybrid_command(name="ship",description="Ship two members.")
async def ship(ctx,a:discord.Member,b:Optional[discord.Member]=None):
    b=b or ctx.author; score=random.randint(0,100); await ctx.send(f"💘 {a.display_name} + {b.display_name} = **{score}%** compatibility!")

@bot.hybrid_command(name="roast",description="Give a playful roast.")
async def roast(ctx,member:Optional[discord.Member]=None): await ctx.send(f"🔥 {member or ctx.author.mention}: You're the reason the loading screen needs a loading screen.")

@bot.hybrid_command(name="compliment",description="Give a compliment.")
async def compliment(ctx,member:Optional[discord.Member]=None): await ctx.send(f"💙 {member or ctx.author.mention}: You're doing better than you think!")

# ---------------- Birthday / QOTD ----------------
@bot.hybrid_command(name="setbirthday",description="Save a birthday month and day.")
@commands.guild_only()
async def setbirthday(ctx,month:int,day:int):
    if not 1<=month<=12 or not 1<=day<=31:return await ctx.send("❌ Invalid month/day.")
    with db: db.execute("INSERT OR REPLACE INTO birthdays VALUES(?,?,?,?)",(ctx.guild.id,ctx.author.id,month,day))
    await ctx.send(f"🎂 Birthday saved: `{month}/{day}`")

@bot.hybrid_command(name="birthday",description="Show a member's saved birthday.")
@commands.guild_only()
async def birthday(ctx,member:Optional[discord.Member]=None):
    m=member or ctx.author; r=db.execute("SELECT month,day FROM birthdays WHERE guild_id=? AND user_id=?",(ctx.guild.id,m.id)).fetchone(); await ctx.send(f"🎂 {m.mention}: **{r['month']}/{r['day']}**" if r else "No birthday saved.")

QOTDS=["What game could you play forever?","What anime character would you want as a teammate?","What is one skill you want to master?"]
@bot.hybrid_command(name="setqotd",description="Set the QOTD channel.")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def setqotd(ctx,channel:discord.TextChannel): set_setting(ctx.guild.id,"qotd_channel",channel.id); await ctx.send(f"✅ QOTD channel: {channel.mention}")

@bot.hybrid_command(name="qotd",description="Post a question of the day.")
@commands.guild_only()
async def qotd(ctx):
    s=settings(ctx.guild.id); channel=ctx.guild.get_channel(s["qotd_channel"]) if s["qotd_channel"] else ctx.channel; await channel.send(f"❓ **Question of the Day:** {random.choice(QOTDS)}")

# ---------------- Errors / start ----------------
@bot.event
async def on_command_error(ctx,error):
    if isinstance(error,commands.CommandNotFound):return
    if isinstance(error,commands.MissingPermissions):return await ctx.send("❌ You don't have permission to use that command.")
    if isinstance(error,commands.BotMissingPermissions):return await ctx.send("❌ I need more permissions to do that.")
    if isinstance(error,commands.MissingRequiredArgument):return await ctx.send(f"❌ Missing argument `{error.param.name}`. Try `{settings(ctx.guild.id)['prefix'] if ctx.guild else DEFAULT_PREFIX}help`.")
    if isinstance(error,commands.BadArgument):return await ctx.send("❌ Invalid argument. Check the member/channel/role/number.")
    print("Prefix error:",repr(error)); await ctx.send("⚠️ Something went wrong.")

@bot.tree.error
async def on_app_error(interaction,error):
    original=getattr(error,"original",error)
    if isinstance(original,app_commands.MissingPermissions): msg="❌ You don't have permission to use that command."
    else: print("Slash error:",repr(original)); msg="⚠️ Something went wrong."
    try:
        if interaction.response.is_done(): await interaction.followup.send(msg,ephemeral=True)
        else: await interaction.response.send_message(msg,ephemeral=True)
    except discord.HTTPException: pass

if __name__ == "__main__":
    keep_alive()
    bot.run(TOKEN)
