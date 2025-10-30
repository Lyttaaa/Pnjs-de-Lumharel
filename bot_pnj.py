# bot_pnj.py — PNJ d’interaction Lumharel (version stabilisée)
import os
import json
import random
import logging
import unicodedata
from typing import Dict, Any, Optional, List

import discord
from discord.ext import commands
import aiohttp

# --- Mongo safe/tolérant ---
try:
    from pymongo import MongoClient
except ImportError:
    MongoClient = None

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("pnj-bot")

PNJS_PATH   = os.getenv("PNJS_PATH",   "pnjs.json")
QUETES_PATH = os.getenv("QUETES_PATH", "quetes.json")

INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.reactions = True
INTENTS.guilds = True

bot = commands.Bot(
    command_prefix="!",
    intents=INTENTS,
    allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=False),
)

# ================
#  MongoDB init
# ================
MONGO_URI = os.getenv("MONGO_URI")
print(f"[BOOT] PNJ MONGO_URI {'OK' if MONGO_URI else 'ABSENT'}")

mongo_client = None
db = None
user_state = None
try:
    if MongoClient and MONGO_URI:
        mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        mongo_client.admin.command("ping")
        db = mongo_client.get_database("lumharel_bot")
        user_state = db.user_state
        print("[INFO] MongoDB OK pour le PNJ.")
    else:
        print("[WARN] Mongo OFF (pymongo manquant ou MONGO_URI absent). Fallback mémoire.")
except Exception as e:
    print(f"[WARN] Mongo OFF ({e}). Fallback mémoire.")
    mongo_client = None
    db = None
    user_state = None

# Fallback mémoire si Mongo OFF (utile en test)
ACTIVE_STATE: Dict[str, Dict[str, Any]] = {}

def get_active_interaction(user_id: int) -> Optional[Dict[str, Any]]:
    if user_state is not None:
        doc = user_state.find_one({"_id": str(user_id)}, {"active_interaction": 1})
        return (doc or {}).get("active_interaction")
    return (ACTIVE_STATE.get(str(user_id)) or {}).get("active_interaction")

def set_active_interaction(user_id: int, patch: Dict[str, Any]) -> None:
    if user_state is not None:
        user_state.update_one({"_id": str(user_id)},
                              {"$set": {f"active_interaction.{k}": v for k, v in patch.items()}},
                              upsert=True)
        return
    rec = ACTIVE_STATE.setdefault(str(user_id), {"active_interaction": {}})
    rec["active_interaction"].update(patch)

def clear_active_interaction(user_id: int) -> None:
    if user_state is not None:
        user_state.update_one({"_id": str(user_id)}, {"$unset": {"active_interaction": ""}})
        return
    if str(user_id) in ACTIVE_STATE:
        ACTIVE_STATE[str(user_id)].pop("active_interaction", None)

# ================
#  Chargement data
# ================
def charger_pnjs() -> Dict[str, Any]:
    with open(PNJS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {str(k).strip(): v for k, v in data.items()}

def charger_quetes_raw() -> Dict[str, Any]:
    with open(QUETES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def indexer_quetes_par_id(quetes_raw: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    index = {}
    for key, val in quetes_raw.items():
        if isinstance(val, list):
            for q in val:
                qid = (q.get("id") or "").upper()
                if qid:
                    index[qid] = q
    return index

def charger_quete_par_id(quest_id: str) -> Optional[Dict[str, Any]]:
    return QUETES_INDEX.get((quest_id or "").upper())

pnjs: Dict[str, Any] = charger_pnjs()
QUETES_RAW: Dict[str, Any] = charger_quetes_raw()
QUETES_INDEX: Dict[str, Dict[str, Any]] = indexer_quetes_par_id(QUETES_RAW)

log.info(f"PNJs chargés: {list(pnjs.keys())}")
log.info(f"Quêtes indexées: {len(QUETES_INDEX)}")

# ================
#  Utils
# ================
dernieres_repliques: Dict[tuple, str] = {}

def _normalize_text(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = s.lower().strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("’", "'").replace("\u200b", "")
    return s

def _channel_match(message: discord.Message, step_or_quest: Dict[str, Any]) -> bool:
    """Accepte 'channel' (nom) OU 'channel_id' (int ou str)."""
    expected_name = _normalize_text(step_or_quest.get("channel", ""))
    expected_id = step_or_quest.get("channel_id")
    if expected_id:
        try:
            if int(expected_id) == message.channel.id:
                return True
        except Exception:
            pass
    if expected_name:
        return _normalize_text(getattr(message.channel, "name", "")) == expected_name
    return True  # si rien n'est précisé

def _keywords_match(content: str, keywords: List[str]) -> bool:
    if not keywords:
        return True
    ncontent = _normalize_text(content)
    return all(_normalize_text(k) in ncontent for k in keywords)

async def envoyer_replique_pnj(pnj_name: str, pnj_data: Dict[str, Any], contenu: str) -> None:
    webhook_env = pnj_data.get("webhook_env", "")
    webhook_url = os.getenv(webhook_env)
    if not webhook_url:
        log.warning(f"Webhook manquant pour PNJ '{pnj_name}' (env {webhook_env})")
        return
    async with aiohttp.ClientSession() as session:
        webhook = discord.Webhook.from_url(webhook_url, session=session)
        await webhook.send(content=contenu, username=pnj_data.get("nom_affiche", pnj_name))

def choisir_fallback_pnj(pnj_name: str, pnj_data: Dict[str, Any], quest_id: str, user_id: int) -> str:
    pool = pnj_data.get("repliques") or [f"{pnj_data.get('nom_affiche','PNJ')} te salue, {{user}}."]
    derniere = dernieres_repliques.get((pnj_name, quest_id, user_id))
    candidats = [r for r in pool if r != derniere] or pool
    texte = random.choice(candidats)
    dernieres_repliques[(pnj_name, quest_id, user_id)] = texte
    return texte

def _get_step(quete: Dict[str, Any], current_step: Optional[int]) -> Optional[Dict[str, Any]]:
    steps = quete.get("steps", [])
    if not steps:
        return None
    idx = (int(current_step) - 1) if current_step else 0
    if idx < 0 or idx >= len(steps):
        idx = 0
    return steps[idx]

def _has_next_step(quete: Dict[str, Any], current_step: Optional[int]) -> bool:
    steps = quete.get("steps", [])
    if not steps:
        return False
    idx = (int(current_step) - 1) if current_step else 0
    return (idx + 1) < len(steps)

# ================
#  Events & cmds
# ================
@bot.event
async def on_ready():
    log.info(f"Connectée en tant que {bot.user} (PNJ bot)")
    await bot.change_presence(activity=discord.Game(name="Lumharel — PNJ"))

@bot.command(name="debug_interaction")
async def debug_interaction(ctx: commands.Context):
    state = get_active_interaction(ctx.author.id)
    await ctx.reply(f"active_interaction = `{state}`")

@bot.command(name="reset_interaction")
async def reset_interaction(ctx: commands.Context):
    clear_active_interaction(ctx.author.id)
    await ctx.reply("Interaction active effacée.")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    contenu = message.content or ""
    state = get_active_interaction(message.author.id)
    if not state:
        await bot.process_commands(message)
        return

    quest_id = state.get("quest_id")
    pnj_name = (state.get("pnj") or "").strip()
    awaiting_reaction = bool(state.get("awaiting_reaction"))
    current_step = state.get("current_step")

    quete = charger_quete_par_id(quest_id)
    if not quete:
        log.warning(f"Quête {quest_id} introuvable dans {QUETES_PATH}")
        await bot.process_commands(message)
        return

    if pnj_name not in pnjs:
        log.warning(f"PNJ '{pnj_name}' introuvable dans {PNJS_PATH}")
        await bot.process_commands(message)
        return
    pnj_data = pnjs[pnj_name]

    # Si on attend une réaction, ne rien faire tant que la réaction n'est pas arrivée
    if awaiting_reaction:
        await bot.process_commands(message)
        return

    qtype = quete.get("type", "interaction")

    # --- Interaction simple ---
    if qtype != "multi_step":
        if not _channel_match(message, quete):
            await bot.process_commands(message)
            return

        keywords = quete.get("mots_cles") or []
        if not _keywords_match(contenu, keywords):
            await bot.process_commands(message)
            return

        texte = (quete.get("replique_pnj") or "").strip() or \
                choisir_fallback_pnj(pnj_name, pnj_data, quest_id, message.author.id)
        texte = texte.format(user=message.author.mention)
        await envoyer_replique_pnj(pnj_name, pnj_data, texte)

        emoji_root = quete.get("emoji")
        if emoji_root:
            set_active_interaction(message.author.id, {"awaiting_reaction": True, "emoji": emoji_root})
            try:
                await message.channel.send(
                    f"(Pour valider, réagis avec {emoji_root} sur le message du {pnj_data.get('nom_affiche','PNJ')} 😉)"
                )
            except Exception:
                pass
        else:
            clear_active_interaction(message.author.id)

        await bot.process_commands(message)
        return

    # --- Multi-étapes ---
    step = _get_step(quete, current_step)
    if not step:
        # Pas d'étape définie => on clear
        clear_active_interaction(message.author.id)
        await bot.process_commands(message)
        return

    if not _channel_match(message, step):
        await bot.process_commands(message)
        return

    step_keywords = step.get("mots_cles") or []
    if not _keywords_match(contenu, step_keywords):
        await bot.process_commands(message)
        return

    texte = (step.get("replique_pnj") or "").strip() or \
            choisir_fallback_pnj(pnj_name, pnj_data, quest_id, message.author.id)
    texte = texte.format(user=message.author.mention)
    await envoyer_replique_pnj(pnj_name, pnj_data, texte)

    if step.get("emoji"):
        set_active_interaction(message.author.id, {"awaiting_reaction": True, "emoji": step["emoji"]})
        try:
            await message.channel.send(
                f"(Pour valider, réagis avec {step['emoji']} sur le message du {pnj_data.get('nom_affiche','PNJ')} 😉)"
            )
        except Exception:
            pass
    else:
        if _has_next_step(quete, current_step):
            next_step = (int(current_step) if current_step else 1) + 1
            set_active_interaction(message.author.id, {"current_step": next_step})
        else:
            clear_active_interaction(message.author.id)

    await bot.process_commands(message)

# --- Réactions pour avancer une étape (utile pour étapes intermédiaires avec emoji)
@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return
    emoji = str(payload.emoji)

    # Récupérer l'état
    state = get_active_interaction(payload.user_id)
    if not state or not state.get("awaiting_reaction"):
        return

    quest_id = state.get("quest_id")
    quete = charger_quete_par_id(quest_id)
    if not quete:
        return

    # Vérifier si l'emoji correspond à l'étape courante (ou à l'interaction simple)
    expected = state.get("emoji")
    if not expected:
        # fallback: lire depuis quete/step si pas mémorisé
        if quete.get("type") == "multi_step":
            step = _get_step(quete, state.get("current_step"))
            expected = step.get("emoji") if step else None
        else:
            expected = quete.get("emoji")

    if not expected or emoji != expected:
        return

    # Si on a une étape suivante -> avancer ; sinon clear (Maître des Quêtes récompensera)
    if quete.get("type") == "multi_step" and _has_next_step(quete, state.get("current_step")):
        next_step = (int(state.get("current_step") or 1)) + 1
        set_active_interaction(payload.user_id, {"current_step": next_step, "awaiting_reaction": False, "emoji": None})
    else:
        clear_active_interaction(payload.user_id)

# ================
#  RUN
# ================
def main():
    token = (
        os.getenv("DISCORD_TOKEN_PNJ") or  # ton nom actuel
        os.getenv("PNJ_BOT_TOKEN") or     # ancien nom si tu préfères
        os.getenv("DISCORD_TOKEN")        # fallback
    )
    if not token:
        raise RuntimeError("Token manquant (DISCORD_TOKEN_PNJ / PNJ_BOT_TOKEN / DISCORD_TOKEN).")
    if not MONGO_URI:
        log.warning("MONGO_URI non défini : le PNJ utilisera le fallback mémoire (pas de partage d'état).")
    bot.run(token)

if __name__ == "__main__":
    main()
