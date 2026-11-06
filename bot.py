import asyncio
from telegram.ext import Application
from config import BOT_TOKEN
from database import init_db
from handlers import register_handlers
from keep_alive import keep_alive

async def post_init(application):
    await init_db()

def main():
    keep_alive()
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    register_handlers(application)
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
