import discord
from discord.ext import commands
from discord import app_commands
import os, time, asyncio, sqlite3
from collections import defaultdict, deque
from datetime import timedelta
from keep_alive import keep_alive
keep_alive()

# =====================
# CONFIG
# =====================
TOKEN = os.getenv("TOKEN")  
LOG_CHANNEL = "security-logs"

NUKE_LIMIT = 2
NUKE_TIME = 5

# =====================
# DATABASE
# =====================
db = sqlite3.connect("security.db")
cur = db.cursor()

cur.execute("CREATE TABLE IF NOT EXISTS whitelist (user_id INTEGER PRIMARY KEY)")
cur.execute("CREATE TABLE IF NOT EXISTS global_bans (user_id INTEGER PRIMARY KEY)")
db.commit()

WHITELIST = {r[0] for r in cur.execute("SELECT user_id FROM whitelist")}
GLOBAL_BANS = {r[0] for r in cur.execute("SELECT user_id FROM global_bans")}

# =====================
# BOT
# =====================
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

nuke_tracker = defaultdict(deque)

# =====================
# UTILS
# =====================
def whitelisted(member):
    return (
        member.id in WHITELIST or
        member.id == member.guild.owner_id or
        member.bot
    )

async def log(guild, title, desc, color):
    ch = discord.utils.get(guild.text_channels, name=LOG_CHANNEL)
    if not ch:
        return
    embed = discord.Embed(
        title=title,
        description=desc,
        color=color,
        timestamp=discord.utils.utcnow()
    )
    await ch.send(embed=embed)

# =====================
# ANTI NUKE
# =====================
async def anti_nuke(guild, user, reason):
    if not user or user.bot:
        return
    if user.id == guild.owner_id or user.id in WHITELIST:
        return

    now = time.time()
    t = nuke_tracker[user.id]
    t.append(now)

    while t and now - t[0] > NUKE_TIME:
        t.popleft()

    if len(t) >= NUKE_LIMIT:
        try:
            await guild.ban(user, reason=f"ANTI NUKE: {reason}")
            await log(
                guild,
                "🚨 ANTI NUKE",
                f"User: `{user}`\nReason: `{reason}`",
                discord.Color.red()
            )
        except Exception as e:
            print("ANTI NUKE FAIL:", e)
        t.clear()

# =====================
# EVENTS (NUKE)
# =====================
@bot.event
async def on_guild_channel_create(channel):
    await asyncio.sleep(0.6)
    async for e in channel.guild.audit_logs(
        limit=5,
        action=discord.AuditLogAction.channel_create
    ):
        await anti_nuke(channel.guild, e.user, "CHANNEL CREATE")
        break

@bot.event
async def on_guild_role_create(role):
    await asyncio.sleep(0.6)
    async for e in role.guild.audit_logs(
        limit=5,
        action=discord.AuditLogAction.role_create
    ):
        await anti_nuke(role.guild, e.user, "ROLE CREATE")
        break

@bot.event
async def on_guild_role_delete(role):
    await asyncio.sleep(0.6)
    async for e in role.guild.audit_logs(
        limit=5,
        action=discord.AuditLogAction.role_delete
    ):
        await anti_nuke(role.guild, e.user, "ROLE DELETE")
        break

# =====================
# JOIN GLOBAL BAN CHECK
# =====================
@bot.event
async def on_member_join(member):
    if member.id in GLOBAL_BANS:
        await member.ban(reason="GLOBAL BAN")
        await log(
            member.guild,
            "🌍 GLOBAL BAN",
            f"Auto banned `{member}`",
            discord.Color.red()
        )

# =====================
# SLASH COMMANDS
# =====================

# --- WHITELIST ---
@bot.tree.command(name="whitelist")
@app_commands.checks.has_permissions(administrator=True)
async def whitelist_add(inter: discord.Interaction, user: discord.Member):
    WHITELIST.add(user.id)
    cur.execute("INSERT OR IGNORE INTO whitelist VALUES (?)", (user.id,))
    db.commit()
    await inter.response.send_message("✅ Whitelisted", ephemeral=True)

@bot.tree.command(name="whitelist_remove")
@app_commands.checks.has_permissions(administrator=True)
async def whitelist_remove(inter: discord.Interaction, user: discord.Member):
    WHITELIST.discard(user.id)
    cur.execute("DELETE FROM whitelist WHERE user_id = ?", (user.id,))
    db.commit()
    await inter.response.send_message("❌ Removed", ephemeral=True)

@bot.tree.command(name="whitelist_list")
@app_commands.checks.has_permissions(administrator=True)
async def whitelist_list(inter: discord.Interaction):
    if not WHITELIST:
        return await inter.response.send_message("Empty", ephemeral=True)
    await inter.response.send_message(
        "\n".join(f"• `{u}`" for u in WHITELIST)[:1900],
        ephemeral=True
    )

# --- KICK / BAN ---
@bot.tree.command(name="kick")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(inter: discord.Interaction, user: discord.Member, reason: str = "Kick"):
    if whitelisted(user):
        return await inter.response.send_message("❌ Cannot kick", ephemeral=True)
    await user.kick(reason=reason)
    await log(inter.guild, "👢 Kick", f"{user}\nReason: {reason}", discord.Color.orange())
    await inter.response.send_message("👢 Kicked", ephemeral=True)

@bot.tree.command(name="ban")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(inter: discord.Interaction, user: discord.Member, reason: str = "Ban"):
    if whitelisted(user):
        return await inter.response.send_message("❌ Cannot ban", ephemeral=True)
    await user.ban(reason=reason)
    await log(inter.guild, "⛔ Ban", f"{user}\nReason: {reason}", discord.Color.red())
    await inter.response.send_message("⛔ Banned", ephemeral=True)

@bot.tree.command(name="unban")
@app_commands.checks.has_permissions(ban_members=True)
async def unban(inter: discord.Interaction, user_id: str):
    uid = int(user_id)
    await inter.guild.unban(discord.Object(id=uid))
    await log(inter.guild, "🟢 Unban", f"User ID `{uid}`", discord.Color.green())
    await inter.response.send_message("🟢 Unbanned", ephemeral=True)

# --- GLOBAL BAN ---
@bot.tree.command(name="globalban")
@app_commands.checks.has_permissions(administrator=True)
async def globalban(inter: discord.Interaction, user_id: str, reason: str = "Global Ban"):
    uid = int(user_id)
    GLOBAL_BANS.add(uid)
    cur.execute("INSERT OR IGNORE INTO global_bans VALUES (?)", (uid,))
    db.commit()

    count = 0
    for g in bot.guilds:
        m = g.get_member(uid)
        if m:
            try:
                await g.ban(m, reason=reason)
                count += 1
            except:
                pass

    await log(inter.guild, "🌍 GLOBAL BAN", f"User ID `{uid}`\nServers `{count}`", discord.Color.red())
    await inter.response.send_message("🌍 Global banned", ephemeral=True)

@bot.tree.command(name="globalunban")
@app_commands.checks.has_permissions(administrator=True)
async def globalunban(inter: discord.Interaction, user_id: str):
    uid = int(user_id)
    GLOBAL_BANS.discard(uid)
    cur.execute("DELETE FROM global_bans WHERE user_id = ?", (uid,))
    db.commit()

    for g in bot.guilds:
        try:
            await g.unban(discord.Object(id=uid))
        except:
            pass

    await log(inter.guild, "🟢 GLOBAL UNBAN", f"User ID `{uid}`", discord.Color.green())
    await inter.response.send_message("🟢 Global unbanned", ephemeral=True)

@bot.tree.command(name="globalban_list")
@app_commands.checks.has_permissions(administrator=True)
async def globalban_list(inter: discord.Interaction):
    if not GLOBAL_BANS:
        return await inter.response.send_message("No global bans", ephemeral=True)
    await inter.response.send_message(
        "\n".join(f"• `{u}`" for u in GLOBAL_BANS)[:1900],
        ephemeral=True
    )

# =====================
# READY
# =====================
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"🟢 Logged in as {bot.user}")

bot.run(TOKEN)
