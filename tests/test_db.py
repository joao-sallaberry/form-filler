# SPDX-License-Identifier: AGPL-3.0-or-later
from form_filler import db


def make(conn, chat_id=1, hora="10:00", dias="1"):
    db.upsert_user(conn, chat_id, nome="A B", telefone="11999999999", email="a@b.c",
                   instagram="", unidade="PD Pinheiros", hora_lembrete=hora, dias=dias)


def test_due_and_idempotent():
    conn = db.connect(":memory:")
    make(conn, 1, "10:00")
    make(conn, 2, "12:00")
    assert [r["chat_id"] for r in db.due_users(conn, "2026-11-10", "10:00")] == [1]
    db.mark_asked(conn, 1, "2026-11-10")
    assert db.due_users(conn, "2026-11-10", "11:00") == []
    assert [r["chat_id"] for r in db.due_users(conn, "2026-11-10", "13:00")] == [2]
    db.mark_skipped(conn, 2, "2026-11-10", "sem_opcao")
    assert db.due_users(conn, "2026-11-10", "13:00") == []
    assert db.get_ask(conn, 2, "2026-11-10")["resposta"] == "sem_opcao"


def test_paused():
    conn = db.connect(":memory:")
    make(conn)
    db.set_field(conn, 1, "ativo", 0)
    assert db.due_users(conn, "2026-11-10", "11:00") == []
    db.set_field(conn, 1, "ativo", 1)
    assert len(db.due_users(conn, "2026-11-10", "11:00")) == 1


def test_record_answer():
    conn = db.connect(":memory:")
    make(conn)
    db.record_answer(conn, 1, "2026-11-10", "sim", opcao="X", enviado=True)
    a = db.get_ask(conn, 1, "2026-11-10")
    assert a["resposta"] == "sim" and a["enviado_em"] and a["opcao"] == "X"
    db.delete_user(conn, 1)
    assert db.get_user(conn, 1) is None


def test_recadastro_atualiza_dias():
    conn = db.connect(":memory:")
    make(conn, 1, dias="1")
    make(conn, 1, dias="1,2")
    assert db.get_user(conn, 1)["dias"] == "1,2"
