import os
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command(commands=['start']))
async def cmd_start(message: types.Message):
    await message.reply("🚀 Welcome to AutoYHack Bot!")

@dp.message(Command(commands=['help']))
async def cmd_help(message: types.Message):
    await message.reply("🤖 Help section")

if __name__ == "__main__":
    dp.run_polling(bot)
