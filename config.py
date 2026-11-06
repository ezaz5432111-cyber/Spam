import os

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])
SMM_API_URL = os.environ["SMM_API_URL"]
SMM_API_KEY = os.environ["SMM_API_KEY"]
DB_PATH = os.environ["DB_PATH"]
PORT = int(os.environ.get("PORT", "10000"))
