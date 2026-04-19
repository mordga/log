import os
import discord
from discord.ext import commands
import requests
from dotenv import load_dotenv

load_dotenv()

DISCORD_BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
HOOK_TOKEN = os.environ.get('HOOK_TOKEN')
PUBLIC_BASE = os.environ.get('PUBLIC_BASE', 'https://tu-proyecto.vercel.app')

if not DISCORD_BOT_TOKEN:
    print("❌ DISCORD_BOT_TOKEN no configurado en .env")
    exit(1)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} comandos sincronizados")
    except Exception as e:
        print(f"❌ Error sincronizando: {e}")

@bot.tree.command(name="track", description="Crear un link tracked")
async def track(
    interaction: discord.Interaction,
    url: str,
    prefer: str = "auto",
    name: str = None
):
    """Crea un short link tracked"""
    await interaction.response.defer(ephemeral=True)
    
    try:
        convert_url = f"{PUBLIC_BASE}/convert"
        
        payload = {
            "url": url,
            "prefer": prefer,
            "name": name
        }
        
        response = requests.post(
            convert_url,
            json=payload,
            headers={"x-hook-token": HOOK_TOKEN},
            timeout=10
        )
        
        if response.ok:
            data = response.json()
            if data.get("mode") == "redirect":
                short_url = data.get("short_url")
                await interaction.followup.send(
                    f"✅ **Short URL creada:**\n```\n{short_url}\n```",
                    ephemeral=True
                )
            else:
                appended = data.get("appended_url")
                await interaction.followup.send(
                    f"✅ **URL append:**\n```\n{appended}\n```",
                    ephemeral=True
                )
        else:
            error = response.json().get("error", "Unknown error")
            await interaction.followup.send(
                f"❌ Error: {error}",
                ephemeral=True
            )
    except Exception as e:
        await interaction.followup.send(
            f"❌ Error: {str(e)}",
            ephemeral=True
        )

bot.run(DISCORD_BOT_TOKEN)
