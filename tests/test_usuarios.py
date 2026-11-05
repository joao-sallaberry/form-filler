# SPDX-License-Identifier: AGPL-3.0-or-later
from form_filler import db, usuarios


def test_vazio():
    conn = db.connect(":memory:")
    assert usuarios.formatar(usuarios.linhas(conn)) == "Nenhum usuário cadastrado."


def test_lista():
    conn = db.connect(":memory:")
    db.upsert_user(conn, 1, nome="Ana Lima", telefone="11999999999", email="a@b.c",
                   instagram="@ana", unidade="PD Pinheiros", hora_lembrete="10:00", dias="1,2")
    db.upsert_user(conn, 2, nome="Bia", telefone="11888888888", email="b@b.c",
                   instagram="", unidade="PD Paulista", hora_lembrete="12:30", dias="2")
    db.set_field(conn, 2, "ativo", 0)
    saida = usuarios.formatar(usuarios.linhas(conn))
    assert "Ana Lima" in saida and "terça e quarta" in saida and "ativo" in saida
    assert "Bia" in saida and "pausado" in saida
    assert saida.endswith("2 usuário(s), 1 ativo(s).")
