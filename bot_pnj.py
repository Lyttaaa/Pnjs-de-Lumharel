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

    for nom_pnj, data in pnjs.items():
        mention_nom = nom_pnj.lower() in contenu
        mention_role = any(role.name.lower() == nom_pnj.lower() for role in message.role_mentions)
        mot_clef_trouve = any(mot in contenu for mot in data["mots_cles"])

        if (mention_nom or mention_role) and mot_clef_trouve:
            webhook_url = os.getenv(data["webhook_env"])
            if not webhook_url:
                print(f"⚠️ Webhook non défini pour {nom_pnj}")
                continue

            async with aiohttp.ClientSession() as session:
                webhook = discord.Webhook.from_url(webhook_url, session=session)

                reponse = random.choice(data["repliques"]).format(user=message.author.mention)

                await webhook.send(
                    content=reponse,
                    username=data["nom_affiche"]  # Peut être remplacé si tu veux varier les noms
                )

    await bot.process_commands(message)

bot.run(os.getenv("DISCORD_TOKEN_PNJ"))
