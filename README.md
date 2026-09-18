# Omni Cave V2

## Render bot
Build command:
`pip install -r requirements.txt`

Start command:
`python bot.py`

Environment variables:
- `DISCORD_TOKEN` = your Discord bot token
- `GEMINI_API_KEY` = your Google Gemini API key
- `DEV_GUILD_ID` = optional server ID for instant slash-command testing
- `WELCOME_CHANNEL_ID` = optional welcome channel ID
- `GOODBYE_CHANNEL_ID` = optional goodbye channel ID

In Discord Developer Portal, enable:
- Server Members Intent
- Message Content Intent

Invite the bot with both `bot` and `applications.commands` scopes.

## Website
The Flask app serves `website/index.html` from the same Render service.
The root URL shows the Omni Cave website and `/health` returns a health check.

## Important
SQLite is local to the Render instance. For permanent production data after restarts/redeploys, move the database to a persistent disk or external database.
