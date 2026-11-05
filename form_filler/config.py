# SPDX-License-Identifier: AGPL-3.0-or-later
import os
from datetime import time
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

FORM_BASE = "https://docs.google.com/forms/d/e/1FAIpQLSf6db3VXp6TU3z7VSFDO5rfbOK90RPx-uF2wYkHbaKFNAKv_A"
VIEW_URL = f"{FORM_BASE}/viewform"
SUBMIT_URL = f"{FORM_BASE}/formResponse"

# entry IDs do formulário
ENTRY_UNIDADE = "1370842096"
ENTRY_DATA = "204293368"
ENTRY_NOME = "1120590305"
ENTRY_INSTAGRAM = "148587811"
ENTRY_TELEFONE = "730700876"

TZ = ZoneInfo("America/Sao_Paulo")
DEADLINE = time(15, 0)  # envio deve chegar até as 15h
LATEST_REMINDER = time(14, 30)

# dias com evento (0=segunda ... 6=domingo). Terça e quarta.
EVENT_WEEKDAYS = {1: "terça", 2: "quarta"}


def dias_label(dias: str) -> str:
    """'1,2' -> 'terça e quarta' (valor da coluna users.dias)."""
    nomes = [EVENT_WEEKDAYS[int(d)] for d in dias.split(",") if d and int(d) in EVENT_WEEKDAYS]
    return " e ".join(nomes) or "nenhum"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
DB_PATH = os.environ.get("DB_PATH", "data/form-filler.db")
ADMIN_CHAT_ID = int(os.environ["ADMIN_CHAT_ID"]) if os.environ.get("ADMIN_CHAT_ID") else None
FORCE_WEEKDAY = os.environ.get("FORCE_WEEKDAY", "0") == "1"
