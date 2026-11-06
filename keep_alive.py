from flask import Flask
from threading import Thread
from config import PORT

app = Flask(__name__)

@app.get("/")
def health():
    return "OK", 200

@app.get("/health")
def health_check():
    return {"status": "ok"}, 200

def keep_alive():
    Thread(
        target=lambda: app.run(host="0.0.0.0", port=PORT, use_reloader=False),
        daemon=True
    ).start()
