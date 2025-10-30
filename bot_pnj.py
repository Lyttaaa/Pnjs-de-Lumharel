# bot_pnj.py
# PNJ bot pour Lumharel — gère les répliques PNJ pour les quêtes d'interaction (simples & multi-étapes)
PNJS_PATH = "pnjs.json"
QUETES_PATH = "quetes.json"

import os
import json
import random
import logging
from typing import Dict, Any, Optional

import discord
from discord.ext import commands
import aiohttp
from pymongo import MongoClient


# -----------------------------
# Configuration & initialisation
# -----------------------------

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("pnj-bot")

INTENTS = discord.Intents.default()
INTENTS.message_content = True  # nécessaire pour lire le contenu des messages

bot = commands.Bot(
    command_prefix="!",
    intents=INTENTS,
    allowed_mentions=discord.AllowedMentions(
        everyone=False, roles=False, users=True, replied_user=False
    ),
)

# chemins fichiers (env → fallback local)
PNJS_PATH = os.getenv("PNJS_PATH", "pnjs.json")
QUETES_PATH = os.getenv("QUETES_PATH", "quetes.json")

try:
    mongo_client = MongoClient(MONGO_URI) if MONGO_URI else None
    db = mongo_client.get_database("lumharel_bot") if mongo_client is not None else None
    user_state = db.user_state if db is not None else None
    if db is None:
        log.warning("MONGO_URI défini mais DB non accessible (vérifie la chaîne/whitelist IP).")
    else:
        log.info("Connexion MongoDB OK.")
except Exception as e:
    log.warning(f"Échec connexion Mongo: {e}")
    mongo_client = None
    db = None
    user_state = None


# Petit cache anti-répétition de réplique par (pnj, quest, user)
dernieres_repliques: Dict[tuple, str] = {}


# -----------------------------
# Chargement PNJ & Quêtes
# -----------------------------

def charger_pnjs() -> Dict[str, Any]:
    with open(PNJS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    # normaliser les clés (strip)
    return {str(k).strip(): v for k, v in data.items()}


def charger_quetes_raw() -> Dict[str, Any]:
    with open(QUETES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def indexer_quetes_par_id(quetes_raw: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    L'index passe sur toutes les valeurs top-level qui sont des listes
    (ex: "Quêtes Interactions", "Quêtes Interactions (AJOUTS)", etc.)
    et indexe par q['id'].
    """
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


# -----------------------------
# Utilitaires Mongo
# -----------------------------

def get_active_interaction(user_id: int) -> Optional[Dict[str, Any]]:
    if not user_state:
        return None
    doc = user_state.find_one({"_id": str(user_id)}, {"active_interaction": 1})
    return (doc or {}).get("active_interaction")


def set_active_interaction(user_id: int, patch: Dict[str, Any]) -> None:
    if not user_state:
        return
    user_state.update_one(
        {"_id": str(user_id)},
        {"$set": {f"active_interaction.{k}": v for k, v in patch.items()}},
        upsert=True,
    )


def clear_active_interaction(user_id: int) -> None:
    if not user_state:
        return
    user_state.update_one({"_id": str(user_id)}, {"$unset": {"active_interaction": ""}})


# -----------------------------
# Aide : envoi d'une réplique PNJ
# -----------------------------

async def envoyer_replique_pnj(
    pnj_name: str,
    pnj_data: Dict[str, Any],
    contenu: str,
) -> None:
    """Envoie 'contenu' via le webhook défini pour ce PNJ."""
    webhook_env = pnj_data.get("webhook_env", "")
    webhook_url = os.getenv(webhook_env)
    if not webhook_url:
        log.warning(f"Webhook manquant pour PNJ '{pnj_name}' (env {webhook_env})")
        return

    async with aiohttp.ClientSession() as session:
        webhook = discord.Webhook.from_url(webhook_url, session=session)
        await webhook.send(content=contenu, username=pnj_data.get("nom_affiche", pnj_name))


def choisir_fallback_pnj(
    pnj_name: str,
    pnj_data: Dict[str, Any],
    quest_id: str,
    user_id: int,
) -> str:
    """Choisit une réplique générique de fallback depuis pnjs.json."""
    pool = pnj_data.get("repliques") or [f"{pnj_data.get('nom_affiche','PNJ')} te salue, {{user}}."]
    derniere = dernieres_repliques.get((pnj_name, quest_id, user_id))
    candidats = [r for r in pool if r != derniere] or pool
    texte = random.choice(candidats)
    dernieres_repliques[(pnj_name, quest_id, user_id)] = texte
    return texte


# -----------------------------
# Événements & commandes
# -----------------------------

@bot.event
async def on_ready():
    log.info(f"Connectée en tant que {bot.user} (PNJ bot)")
    # petit indicateur de présence
    await bot.change_presence(activity=discord.Game(name="Lumharel — PNJ"))


@bot.command(name="debug_interaction")
async def debug_interaction(ctx: commands.Context):
    """Affiche l'état active_interaction de l'utilisateur."""
    state = get_active_interaction(ctx.author.id)
    await ctx.reply(f"active_interaction = `{state}`")


@bot.command(name="reset_interaction")
async def reset_interaction(ctx: commands.Context):
    """Efface l'état active_interaction de l'utilisateur."""
    clear_active_interaction(ctx.author.id)
    await ctx.reply("Interaction active effacée.")


@bot.event
async def on_message(message: discord.Message):
    # laisser passer les messages du bot lui-même + commandes
    if message.author.bot:
        return

    contenu = (message.content or "").lower()
    channel_name = getattr(message.channel, "name", "").lower()

    # 1) Lire la quête d'interaction active pour cet utilisateur
    state = get_active_interaction(message.author.id)
    if not state:
        await bot.process_commands(message)
        return

    quest_id = state.get("quest_id")
    pnj_name = (state.get("pnj") or "").strip()
    awaiting_reaction = bool(state.get("awaiting_reaction"))
    current_step = state.get("current_step")  # None si interaction simple

    # 2) Charger la quête
    quete = charger_quete_par_id(quest_id)
    if not quete:
        log.warning(f"Quête {quest_id} introuvable dans {QUETES_PATH}")
        await bot.process_commands(message)
        return

    # 3) Charger le PNJ
    if pnj_name not in pnjs:
        log.warning(f"PNJ '{pnj_name}' introuvable dans {PNJS_PATH}")
        await bot.process_commands(message)
        return
    pnj_data = pnjs[pnj_name]

    # 4) Si on attend une réaction (fin d'étape / validation par emoji), on ignore les messages
    if awaiting_reaction:
        await bot.process_commands(message)
        return

    # 5) Brancher selon le type
    qtype = quete.get("type", "interaction")

    # ----- Cas A : Interaction simple -----
    if qtype != "multi_step":
        expected_channel = (quete.get("channel") or "").lower()
        if expected_channel and channel_name != expected_channel:
            await bot.process_commands(message)
            return

        keywords = [k.lower() for k in (quete.get("mots_cles") or [])]
        if keywords and not all(k in contenu for k in keywords):
            await bot.process_commands(message)
            return

        # réplique prioritaire depuis la quête
        texte = (quete.get("replique_pnj") or "").strip()
        if not texte:
            # fallback générique PNJ
            texte = choisir_fallback_pnj(pnj_name, pnj_data, quest_id, message.author.id)
        texte = texte.format(user=message.author.mention)

        await envoyer_replique_pnj(pnj_name, pnj_data, texte)

        # Si la quête simple attend un emoji pour être validée → on passe en attente
        emoji_root = quete.get("emoji")
        if emoji_root:
            set_active_interaction(message.author.id, {
                "awaiting_reaction": True,
                "emoji": emoji_root
            })
            # (optionnel) petit rappel côté système
            try:
                await message.channel.send(f"(Pour valider, réagis avec {emoji_root} sur le message du {pnj_data.get('nom_affiche','PNJ')} 😉)")
            except Exception:
                pass
        else:
            # sinon, on termine l'interaction côté PNJ
            clear_active_interaction(message.author.id)

        await bot.process_commands(message)
        return

    # ----- Cas B : Multi-étapes -----
    steps = quete.get("steps", [])
    step_index = (int(current_step) - 1) if current_step else 0
    if step_index < 0 or step_index >= len(steps):
        step_index = 0

    step = steps[step_index]

    expected_channel = (step.get("channel") or "").lower()
    if expected_channel and channel_name != expected_channel:
        await bot.process_commands(message)
        return

    step_keywords = [k.lower() for k in (step.get("mots_cles") or [])]
    if step_keywords and not all(k in contenu for k in step_keywords):
        await bot.process_commands(message)
        return

    # réplique d'étape (priorité step.replique_pnj)
    texte = (step.get("replique_pnj") or "").strip()
    if not texte:
        # fallback générique PNJ
        texte = choisir_fallback_pnj(pnj_name, pnj_data, quest_id, message.author.id)
    texte = texte.format(user=message.author.mention)

    await envoyer_replique_pnj(pnj_name, pnj_data, texte)

    # Étape qui demande une réaction ?
    if step.get("emoji"):
        set_active_interaction(message.author.id, {
            "awaiting_reaction": True,
            "emoji": step["emoji"]
        })
        try:
            await message.channel.send(
                f"(Pour valider, réagis avec {step['emoji']} sur le message du {pnj_data.get('nom_affiche','PNJ')} 😉)"
            )
        except Exception:
            pass
    else:
        # Avancer à l'étape suivante
        next_step = (step_index + 1) + 1  # 1-based
        if next_step <= len(steps):
            set_active_interaction(message.author.id, {"current_step": next_step})
        else:
            # plus d'étapes → fin côté PNJ
            clear_active_interaction(message.author.id)

    await bot.process_commands(message)


# -----------------------------
# Lancement du bot
# -----------------------------

def main():
    token = os.getenv("DISCORD_TOKEN_PNJ")
    if not token:
        raise RuntimeError("Variable d'environnement DISCORD_TOKEN_PNJ manquante.")
    if not mongo_client:
        log.warning("MONGO_URI non défini : le bot PNJ ne pourra pas lire/écrire active_interaction.")
    bot.run(token)


if __name__ == "__main__":
    main()
