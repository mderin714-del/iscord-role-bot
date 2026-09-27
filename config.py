import os
from dotenv import load_dotenv

load_dotenv()

# Токен Discord бота (получается на https://discord.com/developers/applications)
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")

# Путь к файлу базы данных SQLite
DATABASE_PATH = os.getenv("DATABASE_PATH", "bot_database.db")

# Префикс кодов по умолчанию (если генерируется случайный код)
CODE_PREFIX = os.getenv("CODE_PREFIX", "ROLE")
