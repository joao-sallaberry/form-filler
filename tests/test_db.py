# SPDX-License-Identifier: AGPL-3.0-or-later
from form_filler import db


def make(conn, chat_id=1, hora="10:00", dias="1"):
    db.upsert_user(conn, chat_id, nome="A B", telefone="11999999999", email="a@b.c",
                   instagram="", unidade="PD Pinheiros", hora_lembrete=hora, dias=dias)


def test_due_and_idempotent():
    conn = db.connect(":memory:")
    make(conn, 1, "10:00")
    make(conn, 2, "12:00")
    assert [r["chat_id"] for r in db.due_users(conn, "2026-11-10", 1, "10:00")] == [1]
    assert db.due_users(conn, "2026-11-10", 2, "10:00") == []  # quarta, não cadastrado
    db.mark_asked(conn, 1, "2026-11-10")
    assert db.due_users(conn, "2026-11-10", 1, "11:00") == []
    assert [r["chat_id"] for r in db.due_users(conn, "2026-11-10", 1, "13:00")] == [2]


def test_paused_and_force():
    conn = db.connect(":memory:")
    make(conn)
    db.set_field(conn, 1, "ativo", 0)
    assert db.due_users(conn, "2026-11-10", 1, "11:00") == []
    db.set_field(conn, 1, "ativo", 1)
    assert len(db.due_users(conn, "2026-11-09", 0, "11:00", force_weekday=True)) == 1


def test_record_answer():
    conn = db.connect(":memory:")
    make(conn)
    db.record_answer(conn, 1, "2026-11-10", "sim", opcao="X", enviado=True)
    a = db.get_ask(conn, 1, "2026-11-10")
    assert a["resposta"] == "sim" and a["enviado_em"] and a["opcao"] == "X"
    db.delete_user(conn, 1)
    assert db.get_user(conn, 1) is None


def test_dias_escolhidos():
    conn = db.connect(":memory:")
    make(conn, 1, dias="1")
    make(conn, 2, dias="2")
    make(conn, 3, dias="1,2")
    ids = lambda wd: sorted(r["chat_id"] for r in db.due_users(conn, f"d{wd}", wd, "11:00"))
    assert ids(1) == [1, 3]  # terça
    assert ids(2) == [2, 3]  # quarta
    assert ids(3) == []      # quinta


def test_recadastro_atualiza_dias():
    conn = db.connect(":memory:")
    make(conn, 1, dias="1")
    make(conn, 1, dias="1,2")
    assert db.get_user(conn, 1)["dias"] == "1,2"
