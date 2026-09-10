
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
if __name__ == "__main__":
    keep_alive()
    bot.run(TOKEN)
