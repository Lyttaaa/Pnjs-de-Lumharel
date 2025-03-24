import discord
import os
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN_PNJ")
WEBHOOK_AUBERGISTE = os.getenv("WEBHOOK_AUBERGISTE")

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# 🔁 Réponses possibles de l'Aubergiste
REPONSES_AUBERGISTE = [
    "Salut aventurier·ère ! Merci pour ta livraison, j’vais pouvoir faire mijoter ma fameuse omelette ! 🍳",
    "Oh, t’as trouvé des champignons ? Mets-les là, j’vais m’en occuper.",
    "Encore toi ? T’as une tête qui sent bon l’omelette !"
]

@bot.event
async def on_ready():
    print(f"[PNJ] Connectée en tant que {bot.user}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    contenu = message.content.lower()

    if "aubergiste" in contenu or "<@&NOM_DU_ROLE>" in contenu:  # ou mention exacte du rôle
        # Choisir un message
        from random import choice
        texte = choice(REPONSES_AUBERGISTE)

        # Envoie via webhook
        webhook = discord.Webhook.from_url(WEBHOOK_AUBERGISTE, client=bot.http)
        await webhook.send(
            content=texte,
            username="Aubergiste",
            avatar_url="https://URL_DE_TON_IMAGE_UPLOADÉE.png"
        )

    await bot.process_commands(message)

bot.run(TOKEN)
