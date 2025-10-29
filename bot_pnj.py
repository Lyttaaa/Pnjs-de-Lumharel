import discord
from discord.ext import commands
import os
import aiohttp
import random
import json
from pymongo import MongoClient


# Charger les PNJs
def charger_pnjs():
    with open("pnjs.json", "r", encoding="utf-8") as f:
        return json.load(f)

pnjs = charger_pnjs()
dernieres_repliques = {}  # Dictionnaire pour stocker les dernières répliques par PNJ

# Charger les quêtes (pour lire les "multi_step" et d'autres champs)
def charger_quetes():
    with open("quetes.json", "r", encoding="utf-8") as f:
        return json.load(f)

def indexer_quetes_par_id(quetes_raw):
    index = {}
    for cat, lst in quetes_raw.items():
        if not isinstance(lst, list):
            continue
        for q in lst:
            qid = (q.get("id") or "").upper()
            if qid:
                index[qid] = q
    return index

QUETES_RAW = charger_quetes()
QUETES_INDEX = indexer_quetes_par_id(QUETES_RAW)

def charger_quete_par_id(quest_id: str):
    return QUETES_INDEX.get((quest_id or "").upper())

# --- Mongo (état des joueurs) ---
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI) if MONGO_URI else None
db = client.lumharel_bot if client else None
user_state = db.user_state if db else None

def get_active_interaction(user_id: int):
    if not user_state:
        return None
    doc = user_state.find_one({"_id": str(user_id)}, {"active_interaction": 1})
    return (doc or {}).get("active_interaction")

def set_active_interaction(user_id: int, patch: dict):
    if not user_state:
        return
    user_state.update_one({"_id": str(user_id)}, {"$set": {f"active_interaction.{k}": v for k, v in patch.items()}})

def clear_active_interaction(user_id: int):
    if not user_state:
        return
    user_state.update_one({"_id": str(user_id)}, {"$unset": {"active_interaction": ""}})

# Config bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="?", intents=intents)

@bot.event
async def on_ready():
    print("🎭 Le théâtre des PNJs de Lumharel est prêt !")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    contenu = message.content.lower()
    print(f'\n📩 Nouveau message reçu : "{message.content}" de {message.author.display_name}')

    # 🔒 1) Vérifier s'il y a une interaction active pour CE joueur
    state = get_active_interaction(message.author.id)
    if not state:
        # Aucune quête d'interaction active -> ignorer
        await bot.process_commands(message)
        return

    quest_id = state.get("quest_id")
    pnj_name = (state.get("pnj") or "").strip()
    awaiting_reaction = bool(state.get("awaiting_reaction"))
    current_step = state.get("current_step")  # None pour les interactions simples

    # 2) Charger la quête concernée
    quete = charger_quete_par_id(quest_id)
    if not quete:
        print(f"⚠️ Quête {quest_id} introuvable dans quetes.json")
        await bot.process_commands(message)
        return

    # 3) Récupérer la fiche PNJ
    if pnj_name not in pnjs:
        print(f"⚠️ PNJ {pnj_name} introuvable dans pnjs.json")
        await bot.process_commands(message)
        return
    pnj_data = pnjs[pnj_name]
    webhook_url = os.getenv(pnj_data.get("webhook_env", ""))
    if not webhook_url:
        print(f"⚠️ Webhook non défini pour {pnj_name}")
        await bot.process_commands(message)
        return

    chan = getattr(message.channel, "name", "").lower()

    # 4) Si on est en attente d'une REACTION (fin d'étape) -> ne rien faire ici
    if awaiting_reaction:
        print("— En attente d'une réaction (emoji) pour cette interaction → on ignore les messages.")
        await bot.process_commands(message)
        return

    # 5) Brancher selon le type
    qtype = quete.get("type", "interaction")

    # ---------- Cas A : interaction simple ----------
    if qtype != "multi_step":
        expected_channel = (quete.get("channel") or "").lower()
        if expected_channel and chan != expected_channel:
            print(f"— Mauvais salon (attendu: {expected_channel}) → ignore.")
            await bot.process_commands(message)
            return

        keywords = [k.lower() for k in (quete.get("mots_cles") or [])]
        if keywords and not all(k in contenu for k in keywords):
            print("— Mots-clés non satisfaits → ignore.")
            await bot.process_commands(message)
            return

        # ✅ Conditions OK : réplique prioritaire depuis la quête (replique_pnj), sinon fallback PNJ générique
        texte = (quete.get("replique_pnj") or "").strip()
        if not texte:
            pool = pnj_data.get("repliques") or [f"{pnj_data.get('nom_affiche','PNJ')} te salue, {{user}}."]
            derniere = dernieres_repliques.get((pnj_name, quest_id, message.author.id))
            candidats = [r for r in pool if r != derniere] or pool
            texte = random.choice(candidats)

        texte = texte.format(user=message.author.mention)

        print(f"✅ Interaction simple OK. Envoi de la réplique pour {pnj_name}/{quest_id} : {texte}")

        async with aiohttp.ClientSession() as session:
            webhook = discord.Webhook.from_url(webhook_url, session=session)
            await webhook.send(content=texte, username=pnj_data.get("nom_affiche", "PNJ"))

        # 🧷 Si la quête simple attend une RÉACTION (emoji au niveau racine), on NE clear PAS ici.
        emoji_root = quete.get("emoji")
        if emoji_root:
            set_active_interaction(message.author.id, {
                "awaiting_reaction": True,
                "emoji": emoji_root
            })
        else:
            clear_active_interaction(message.author.id)

        await bot.process_commands(message)
        return

    # ---------- Cas B : multi_step ----------
    steps = quete.get("steps", [])
    step_index = (int(current_step) - 1) if current_step else 0
    if step_index < 0 or step_index >= len(steps):
        step_index = 0

    step = steps[step_index]
    expected_channel = (step.get("channel") or "").lower()
    if expected_channel and chan != expected_channel:
        print(f"— Mauvais salon (attendu: {expected_channel}) → ignore.")
        await bot.process_commands(message)
        return

    step_keywords = [k.lower() for k in (step.get("mots_cles") or [])]
    if step_keywords and not all(k in contenu for k in step_keywords):
        print("— Mots-clés non satisfaits pour l'étape → ignore.")
        await bot.process_commands(message)
        return

    # ✅ Conditions OK : réplique d'étape
    texte = (step.get("replique_pnj") or "").strip()
    if not texte:
        pool = pnj_data.get("repliques") or [f"{pnj_data.get('nom_affiche','PNJ')} te salue, {{user}}."]
        derniere = dernieres_repliques.get((pnj_name, quest_id, message.author.id))
        candidats = [r for r in pool if r != derniere] or pool
        texte = random.choice(candidats)

    texte = texte.format(user=message.author.mention)


    print(f"✅ Étape {step_index+1}/{len(steps)} OK. Envoi de la réplique : {texte}")

    async with aiohttp.ClientSession() as session:
        webhook = discord.Webhook.from_url(webhook_url, session=session)
        await webhook.send(content=texte, username=pnj_data.get("nom_affiche", "PNJ"))

    # Étape demande une réaction ? -> on passe en attente (validée par Maître des Quêtes)
    if step.get("emoji"):
        set_active_interaction(message.author.id, {
            "awaiting_reaction": True,
            "emoji": step["emoji"]
        })
        # (Optionnel) rappeler l'emoji côté bot système :
        try:
            await message.channel.send(f"(Pour valider, réagis avec {step['emoji']} sur le message du {pnj_data.get('nom_affiche','PNJ')} 😉)")
        except Exception:
            pass
    else:
        # Sinon on passe à l'étape suivante, ou on clear si c'était la dernière
        next_step = (step_index + 1) + 1  # étape suivante (1-based)
        if next_step <= len(steps):
            set_active_interaction(message.author.id, {"current_step": next_step})
        else:
            clear_active_interaction(message.author.id)

    await bot.process_commands(message)


bot.run(os.getenv("DISCORD_TOKEN_PNJ"))
