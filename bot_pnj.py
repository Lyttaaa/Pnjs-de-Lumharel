import discord
from discord.ext import commands
import os
import aiohttp
import random

# Webhook configuré depuis Discord (déjà avec image et nom)
WEBHOOK_AUBERGISTE = os.getenv("WEBHOOK_AUBERGISTE")

# Mots-clés pour déclencher une interaction avec l'aubergiste
MOTS_CLEFS_AUBERGISTE = ["livraison", "champignon", "commande", "omelette", "ingrédients", "bonjour", "salut"]

# Répliques immersives aléatoires
REPLIQUES_AUBERGISTE = [
    "Oh merci {user}, j'attendais justement cette livraison 🍄 !",
    "Tu tombes à pic {user} ! Mon omelette de minuit va être parfaite grâce à toi.",
    "Héhé, toujours au rendez-vous toi, {user} ! Allez, bois un coup, c’est offert ! 🍻",
    "Un vrai aventurier, {user} ! Merci pour ces champignons !",
    "Je commençais à m’inquiéter, {user}... Heureusement que t’es là !"
]

# Config du bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="?", intents=intents)

# Fonction de réponse via webhook
async def repondre_aubergiste(message):
    async with aiohttp.ClientSession() as session:
        webhook = discord.Webhook.from_url(WEBHOOK_AUBERGISTE, session=session)

        reponse = random.choice(REPLIQUES_AUBERGISTE).format(user=message.author.mention)

        await webhook.send(
            content=reponse,
            username="Aubergiste de Lumharel"  # Pas nécessaire si déjà défini, mais tu peux le laisser pour forcer
        )

@bot.event
async def on_ready():
    print("🍺 L’Aubergiste est prêt à servir !")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    contenu = message.content.lower()

    # Déclenche si "aubergiste" est mentionné + mot-clé détecté
    mention_nom = "aubergiste" in contenu
    mention_role = any(role.name.lower() == "aubergiste" for role in message.role_mentions)
    mot_clef = any(mot in contenu for mot in MOTS_CLEFS_AUBERGISTE)

    if (mention_nom or mention_role) and mot_clef:
        await repondre_aubergiste(message)

    await bot.process_commands(message)

# Lancement du bot
bot.run(os.getenv("DISCORD_TOKEN_PNJ"))
