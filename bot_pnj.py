import os
import re
import json
import unicodedata
from typing import Any, Dict, Optional, List

import discord
from discord.ext import commands
from discord.utils import get as dget

# ============
#  INTENTS
# ============
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ============
#  CONFIG
# ============
MONGO_URI = os.getenv("MONGO_URI")  # même var que l'autre bot
QUESTS_FILE = os.getenv("CHEMIN_QUETES", "quetes.json")  # même fichier que l'autre bot
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN_PNJ")  # token spécifique PNJ

if not MONGO_URI:
    raise RuntimeError("MONGO_URI est requis pour le bot PNJ.")

# ============
#  MONGO
# ============
from pymongo import MongoClient
client = MongoClient(MONGO_URI)
db = client.get_database("lumharel_bot")

# état d'interaction actif (déposé par le Maître des Quêtes quand on accepte)
user_state           = db.user_state

# ============
#  UTILS
# ============
def _normalize(txt: str) -> str:
    """lower + strip accents + espace normalisé, pour tester les mots-clés de façon robuste."""
    if not isinstance(txt, str):
        return ""
    txt = txt.lower().strip()
    txt = unicodedata.normalize("NFD", txt)
    txt = "".join(c for c in txt if unicodedata.category(c) != "Mn")
    txt = txt.replace("’", "'").replace("\u200b", "")
    txt = re.sub(r"\s+", " ", txt)
    return txt

def load_all_quetes() -> Dict[str, Any]:
    with open(QUESTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def get_quete_by_id(quest_id: str) -> Optional[Dict[str, Any]]:
    quest_id = (quest_id or "").upper().strip()
    data = load_all_quetes()
    for lst in data.values():
        if isinstance(lst, list):
            for q in lst:
                if (q.get("id") or "").upper() == quest_id:
                    return q
    return None

def get_user_state(uid: int | str) -> Optional[Dict[str, Any]]:
    return user_state.find_one({"_id": str(uid)})

def set_active_interaction(uid: int | str, patch: Dict[str, Any]):
    user_state.update_one({"_id": str(uid)}, {"$set": {"active_interaction": {**(get_user_state(uid) or {}).get("active_interaction", {}), **patch}}}, upsert=True)

def clear_active_interaction(uid: int | str):
    user_state.update_one({"_id": str(uid)}, {"$unset": {"active_interaction": ""}})

async def dm_etape(user: discord.User | discord.Member, quete: Dict[str, Any], step_number: int):
    """Envoie en DM un récap de l'étape N (sans spoiler la suivante)."""
    steps: List[Dict[str, Any]] = quete.get("steps") or []
    idx = max(0, min(step_number - 1, len(steps) - 1))
    step = steps[idx]

    embed = discord.Embed(
        title=f"🕹️ Quête Interactions — {quete['id']} • {quete['nom']}",
        description=f"**Étape {step_number}**",
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

    if step.get("replique_pnj"):
        lignes.append(f"• **Indice PNJ** : {step['replique_pnj']}")

    embed.add_field(name="👉 Instructions", value="\n".join(lignes) or "Suis les indications du PNJ.", inline=False)
    try:
        await user.send(embed=embed)
    except discord.Forbidden:
        pass

# ================
#  EVENTS MESSAGES
# ================
@bot.event
async def on_message(message: discord.Message):
    """Détection des messages pour valider les mots-clés de l'étape courante."""
    if message.author.bot:
        return

    state = get_user_state(message.author.id)
    if not state or "active_interaction" not in state:
        await bot.process_commands(message)
        return

    active = state["active_interaction"]
    quete_id = (active.get("quest_id") or "").upper()
    current_step = active.get("current_step", 1)

    # Charger la quête
    quete = get_quete_by_id(quete_id)
    if not quete:
        await bot.process_commands(message)
        return

    # On ne traite que les quêtes d'interactions ici
    qtype = (quete.get("type") or "interaction").strip()
    if qtype not in ("interaction", "multi_step"):
        await bot.process_commands(message)
        return

    steps = quete.get("steps") or []
    # interaction simple => pas d'étapes : on considère step=quete
    if qtype == "multi_step":
        if not steps:
            await bot.process_commands(message)
            return
        step_index = max(0, min((int(current_step) - 1), len(steps) - 1))
        step = steps[step_index]
    else:
        step = quete  # fallback pour simple

    # Matching des mots-clés (sans accents/casse)
    contenu = _normalize(message.content)
    mots = [ _normalize(m) for m in (step.get("mots_cles") or []) ]
    # si des mots-clés sont définis, tous doivent être présents
    if mots and not all(m in contenu for m in mots):
        await bot.process_commands(message)
        return

    # OK mots-clés validés -> réponse PNJ
    rep = (step.get("replique_pnj") or quete.get("description") or "…").replace("{user}", message.author.mention)
    await message.channel.send(rep)

    # Progression
    if qtype == "multi_step":
        # Si l'étape nécessite une réaction, on attend on_raw_reaction_add
        if step.get("emoji"):
            set_active_interaction(message.author.id, {"awaiting_reaction": True})
        else:
            # sinon on passe à l'étape suivante
            if (steps and (step_index + 1) < len(steps)):
                next_step = step_index + 2  # 1-based
                set_active_interaction(message.author.id, {"current_step": next_step, "awaiting_reaction": False, "emoji": None})
                await dm_etape(message.author, quete, next_step)
            else:
                # fin
                clear_active_interaction(message.author.id)
    else:
        # interaction simple, terminé côté PNJ
        clear_active_interaction(message.author.id)

    await bot.process_commands(message)

# =========================
#  EVENTS REACTIONS (emoji)
# =========================
@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return

    # Récup état
    state = get_user_state(payload.user_id)
    if not state or "active_interaction" not in state:
        return

    active = state["active_interaction"]
    quete_id = (active.get("quest_id") or "").upper()
    current_step = active.get("current_step", 1)

    # Charger quête
    quete = get_quete_by_id(quete_id)
    if not quete or (quete.get("type") != "multi_step"):
        return

    steps = quete.get("steps") or []
    if not steps:
        return

    step_index = max(0, min((int(current_step) - 1), len(steps) - 1))
    step = steps[step_index]

    expected = step.get("emoji")
    if not expected:
        return

    # Vérifier l'emoji
    incoming = str(payload.emoji)
    if incoming != expected and getattr(payload.emoji, "name", None) != expected:
        return

    # Valide cette étape
    channel = bot.get_channel(payload.channel_id)
    if channel:
        try:
            msg = await channel.fetch_message(payload.message_id)
            membre = payload.member or (await channel.guild.fetch_member(payload.user_id))
            if membre:
                await msg.channel.send(f"Bien noté {membre.mention} ✅")
        except Exception:
            pass

    # Etape suivante ou fin
    if (step_index + 1) < len(steps):
        next_step = step_index + 2
        set_active_interaction(payload.user_id, {"current_step": next_step, "awaiting_reaction": False, "emoji": None})
        # DM étape suivante
        user = bot.get_user(payload.user_id) or await bot.fetch_user(payload.user_id)
        if user:
            await dm_etape(user, quete, next_step)
    else:
        clear_active_interaction(payload.user_id)

# ====================
#  READY / RUN
# ====================
@bot.event
async def on_ready():
    print(f"✅ Bot PNJ prêt : {bot.user}")

if __name__ == "__main__":
    missing = []
    if not DISCORD_TOKEN: missing.append("DISCORD_TOKEN_PNJ")
    if missing:
        raise RuntimeError(f"Variables manquantes: {', '.join(missing)}")
    bot.run(DISCORD_TOKEN)
