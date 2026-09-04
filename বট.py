import discord
from discord.ext import commands
from datetime import timedelta
import os
from threading import Thread
from flask import Flask
from google import genai
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
app = Flask('')

@app.route('/')
def home():
    return "I'm alive!"

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
@warn.error
async def warn_error(ctx, error):
  if isinstance(error, commands.MissingPermissions):
    await ctx.send("❌ You don't have permission to use this command!")
	  
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
@gogagaga.event
async def on_message(message):
  # Ignore messages sent by the bot itself
  if message.author == gogagaga.user:
    return

  # Check if the bot was explicitly pinged (@mentioned)
  if gogagaga.user in message.mentions:
    # Clean the mention from the user's prompt
    user_prompt = (
        message.content.replace(f'<@{gogagaga.user.id}>', '')
        .replace(f'<@!{gogagaga.user.id}>', '')
        .strip()
    )

    if not user_prompt:
      await message.reply(
          f'Hello {message.author.mention}! How can I help you today?'
      )
      return

    async with message.channel.typing():
      try:
        response = client.models.generate_content(
            model='gemini-3.6-flash',
            contents=user_prompt,
        )

        if response.text:
          await message.reply(response.text)
        else:
          await message.reply('I could not generate a response for that.')

      except Exception as e:
        print(f'Gemini API Error: {e}')
        await message.reply('❌ An error occurred while contacting the AI server.')

    return  # Stop execution here if it was a mention

  # Process prefix commands like !warn or !mute only if bot wasn't pinged
  await gogagaga.process_commands(message)
	
keep_alive()
gogagaga.run(os.getenv("YOUR_TOKEN_HERE"))
