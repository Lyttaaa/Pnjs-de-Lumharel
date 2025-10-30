import discord
from discord.ext import commands
import json
from pymongo import MongoClient
import os

# =========================
# Configuration MongoDB
# =========================
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["lumharel_db"]
user_state = db["user_state"]

# =========================
# Initialisation du bot
# =========================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# =========================
# Utilitaires JSON
# =========================
def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# =========================
# Fonction utilitaire : envoi d'une étape par MP
# =========================
async def dm_etape(user: discord.User, quete: dict, step_number: int):
    """Envoie un DM élégant avec les consignes de l'étape N (1-based)."""
    steps = quete.get("steps", [])
    if not steps or step_number < 1 or step_number > len(steps):
        return
    step = steps[step_number - 1]

    embed = discord.Embed(
        title=f"🔁 Étape {step_number} — {quete.get('nom','Quête')}",
        description=f"**{quete.get('id','')}** — progression",
        color=0x2196F3
    )

    lignes = []
    ch_nom = step.get("channel")
    ch_id = step.get("channel_id")
    if ch_nom:
        lignes.append(f"• **Lieu** : `#{ch_nom}`")
    elif ch_id:
        lignes.append(f"• **Lieu** : <#{ch_id}>")

    mots = step.get("mots_cles") or []
    if mots:
        lignes.append("• **Action** : écris un message contenant : " + ", ".join(f"`{m}`" for m in mots))
    if step.get("emoji"):
        lignes.append(f"• **Validation** : réagis avec {step['emoji']} sur le message du PNJ")

    if not lignes:
        lignes.append("Suis les indications du PNJ.")
    embed.add_field(name="📋 Consignes", value="\n".join(lignes), inline=False)

    try:
        await user.send(embed=embed)
    except Exception:
        pass

# =========================
# Fonctions MongoDB utilitaires
# =========================
def get_user_state(user_id):
    return user_state.find_one({"_id": str(user_id)})

def set_active_interaction(user_id, data):
    user_state.update_one({"_id": str(user_id)}, {"$set": {"active_interaction": data}}, upsert=True)

def clear_active_interaction(user_id):
    user_state.update_one({"_id": str(user_id)}, {"$unset": {"active_interaction": ""}})

def _has_next_step(quete, step_num):
    steps = quete.get("steps", [])
    return step_num is not None and int(step_num) < len(steps)

# =========================
# Événement : message envoyé
# =========================
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    state = get_user_state(message.author.id)
    if not state or "active_interaction" not in state:
        return

    active = state["active_interaction"]
    quete_id = active.get("quest_id")
    current_step = active.get("current_step", 1)

    # Charger la quête correspondante
    try:
        quetes_data = load_json("quetes_interaction.json")
        quete = next((q for q in quetes_data if q["id"] == quete_id), None)
    except Exception:
        quete = None

    if not quete:
        return

    # Vérifier les mots-clés de l'étape actuelle
    step = quete.get("steps", [])[int(current_step) - 1]
    mots = [m.lower() for m in step.get("mots_cles", [])]
    if any(m in message.content.lower() for m in mots):
        await message.channel.send(step.get("replique_pnj", "...").replace("{user}", message.author.mention))

        # Étape suivante ou fin de quête
        if quete.get("type") == "multi_step":
            if _has_next_step(quete, current_step):
                next_step = int(current_step) + 1
                set_active_interaction(message.author.id, {"current_step": next_step})
                # 💌 Envoi de la prochaine étape par MP
                await dm_etape(message.author, quete, next_step)
            else:
                clear_active_interaction(message.author.id)
        else:
            clear_active_interaction(message.author.id)

    await bot.process_commands(message)

# =========================
# Événement : réaction ajoutée
# =========================
@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id:
        return

    state = get_user_state(payload.user_id)
    if not state or "active_interaction" not in state:
        return

    active = state["active_interaction"]
    quete_id = active.get("quest_id")
    current_step = active.get("current_step", 1)

    # Charger la quête
    try:
        quetes_data = load_json("quetes_interaction.json")
        quete = next((q for q in quetes_data if q["id"] == quete_id), None)
    except Exception:
        quete = None

    if not quete:
        return

    # Vérifier si l'étape attend une réaction
    step = quete.get("steps", [])[int(current_step) - 1]
    if payload.emoji.name == step.get("emoji"):
        channel = bot.get_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
        await message.channel.send(f"{bot.user.mention} : Bien joué {payload.member.mention}, c’est noté ! ✅")

        # Étape suivante ou fin de quête
        if quete.get("type") == "multi_step" and _has_next_step(quete, current_step):
            next_step = int(current_step) + 1
            set_active_interaction(payload.user_id, {"current_step": next_step, "awaiting_reaction": False, "emoji": None})
            # 💌 Envoi de la prochaine étape par MP
            user = bot.get_user(payload.user_id) or await bot.fetch_user(payload.user_id)
            if user:
                await dm_etape(user, quete, next_step)
        else:
            clear_active_interaction(payload.user_id)

# =========================
# Lancement du bot
# =========================
TOKEN = os.getenv("DISCORD_TOKEN_PNJ")
bot.run(TOKEN)
