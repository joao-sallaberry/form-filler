# SPDX-License-Identifier: AGPL-3.0-or-later
import os
import sqlite3
from datetime import datetime

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    chat_id       INTEGER PRIMARY KEY,
    nome          TEXT NOT NULL,
    telefone      TEXT NOT NULL,
    email         TEXT NOT NULL,
    instagram     TEXT NOT NULL DEFAULT '',
    unidade       TEXT NOT NULL,
    hora_lembrete TEXT NOT NULL,             -- 'HH:MM'
    dias          TEXT NOT NULL DEFAULT '1', -- weekdays separados por vírgula
    ativo         INTEGER NOT NULL DEFAULT 1,
    criado_em     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS asks (
    chat_id       INTEGER NOT NULL,
    data          TEXT NOT NULL,             -- 'AAAA-MM-DD'
    perguntado_em TEXT,
    resposta      TEXT,                      -- NULL | 'sim' | 'nao'
    enviado_em    TEXT,
    opcao         TEXT,
    erro          TEXT,
    PRIMARY KEY (chat_id, data)
);
"""


def connect(path: str | None = None) -> sqlite3.Connection:
    path = path or config.DB_PATH
    if path != ":memory:":
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        new = not os.path.exists(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # handles do Instagram não diferenciam maiúsculas: guardamos sempre em minúsculas
    conn.execute("UPDATE users SET instagram=lower(instagram) WHERE instagram<>lower(instagram)")
    conn.commit()
    if path != ":memory:" and new:
        os.chmod(path, 0o600)
    return conn


def now_iso() -> str:
    return datetime.now(config.TZ).isoformat(timespec="seconds")


def upsert_user(conn, chat_id: int, **f) -> None:
    f["instagram"] = f["instagram"].lower()
    conn.execute(
        """INSERT INTO users (chat_id, nome, telefone, email, instagram, unidade, hora_lembrete, dias, ativo, criado_em)
           VALUES (:chat_id, :nome, :telefone, :email, :instagram, :unidade, :hora_lembrete, :dias, 1, :criado_em)
           ON CONFLICT(chat_id) DO UPDATE SET nome=excluded.nome, telefone=excluded.telefone,
             email=excluded.email, instagram=excluded.instagram, unidade=excluded.unidade,
             hora_lembrete=excluded.hora_lembrete, dias=excluded.dias, ativo=1""",
        {"chat_id": chat_id, "criado_em": now_iso(), **f},
    )
    conn.commit()


def get_user(conn, chat_id: int):
    return conn.execute("SELECT * FROM users WHERE chat_id=?", (chat_id,)).fetchone()


def set_field(conn, chat_id: int, field: str, value) -> None:
    assert field in {"hora_lembrete", "ativo", "dias"}
    conn.execute(f"UPDATE users SET {field}=? WHERE chat_id=?", (value, chat_id))
    conn.commit()


def delete_user(conn, chat_id: int) -> None:
    conn.execute("DELETE FROM users WHERE chat_id=?", (chat_id,))
    conn.execute("DELETE FROM asks WHERE chat_id=?", (chat_id,))
    conn.commit()


def due_users(conn, day: str, hhmm: str):
    """Usuários ativos cujo lembrete já venceu hoje e que ainda não foram tratados hoje.

    Não filtra pelo dia da semana: quem decide se pergunta é o bot, olhando o formulário.
    """
    return conn.execute(
        """SELECT u.* FROM users u
           WHERE u.ativo=1 AND u.hora_lembrete <= ?
             AND NOT EXISTS (SELECT 1 FROM asks a WHERE a.chat_id=u.chat_id AND a.data=?)""",
        (hhmm, day),
    ).fetchall()


def mark_skipped(conn, chat_id: int, day: str, motivo: str) -> None:
    """Registra que hoje não houve pergunta (ex.: 'sem_opcao', 'fora_dos_dias')."""
    conn.execute(
        "INSERT OR IGNORE INTO asks (chat_id, data, resposta) VALUES (?, ?, ?)",
        (chat_id, day, motivo),
    )
    conn.commit()


def mark_asked(conn, chat_id: int, day: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO asks (chat_id, data, perguntado_em) VALUES (?, ?, ?)",
        (chat_id, day, now_iso()),
    )
    conn.commit()


def get_ask(conn, chat_id: int, day: str):
    return conn.execute("SELECT * FROM asks WHERE chat_id=? AND data=?", (chat_id, day)).fetchone()


def record_answer(conn, chat_id: int, day: str, resposta: str, opcao=None, erro=None, enviado=False) -> None:
    mark_asked(conn, chat_id, day)
    conn.execute(
        "UPDATE asks SET resposta=?, opcao=COALESCE(?, opcao), erro=?, enviado_em=COALESCE(?, enviado_em) "
        "WHERE chat_id=? AND data=?",
        (resposta, opcao, erro, now_iso() if enviado else None, chat_id, day),
    )
    conn.commit()
