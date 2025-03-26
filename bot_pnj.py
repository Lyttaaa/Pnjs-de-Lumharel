import discord
from discord.ext import commands
import os
import aiohttp
import random
import json

# Charger les PNJs
def charger_pnjs():
    with open("pnjs.json", "r", encoding="utf-8") as f:
        return json.load(f)

pnjs = charger_pnjs()
dernieres_repliques = {}  # Dictionnaire pour stocker les dernières répliques par PNJ

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
    print(f"\n📩 Nouveau message reçu : \"{message.content}\" de {message.author.display_name}")

    for nom_pnj, data in pnjs.items():
        print(f"\n🔍 Analyse pour PNJ : {nom_pnj}")

        mention_nom = nom_pnj.lower() in contenu
        mention_role = any(role.name.lower() == nom_pnj.lower() for role in message.role_mentions)
        mot_clef_trouve = any(mot.lower() in contenu for mot in data["mots_cles"])

        print(f"   ➤ Mention nom : {mention_nom}")
        print(f"   ➤ Mention rôle : {mention_role}")
        print(f"   ➤ Mot-clé trouvé : {mot_clef_trouve}")

        if (mention_nom or mention_role) and mot_clef_trouve:
            webhook_url = os.getenv(data["webhook_env"])
            if not webhook_url:
                print(f"⚠️ Webhook non défini pour {nom_pnj}")
                continue

            repliques = data["repliques"]
            derniere = dernieres_repliques.get(nom_pnj)

            # Filtrer pour ne pas reprendre la dernière
            possibles = [r for r in repliques if r != derniere] or repliques
            reponse = random.choice(possibles).format(user=message.author.mention)
            dernieres_repliques[nom_pnj] = reponse  # Mémoriser la nouvelle

            print(f"✅ Conditions remplies ! Envoi de la réplique : {reponse}")

            async with aiohttp.ClientSession() as session:
                webhook = discord.Webhook.from_url(webhook_url, session=session)
                await webhook.send(
                    content=reponse,
                    username=data["nom_affiche"]
                )
        else:
            print(f"❌ Conditions non remplies pour {nom_pnj}")

    await bot.process_commands(message)

bot.run(os.getenv("DISCORD_TOKEN_PNJ"))
