# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio
import os
from datetime import date, datetime
from types import SimpleNamespace

os.environ.setdefault("DB_PATH", ":memory:")

from form_filler import bot, config, db  # noqa: E402
from form_filler.form import SubmitResult  # noqa: E402

OPTS = [
    "Terça feira, 03 de novembro",       # passado
    "Quarta feira, 04 de novembro",      # hoje
    "Terça feira, 10 de novembro",
    "Quinta feira, 12 de novembro",
]
TODAY = date(2026, 11, 4)


class Msg:
    def __init__(self, log):
        self.log = log

    async def reply_text(self, text, reply_markup=None, **kw):
        self.log.append((text, reply_markup))
        return self

    async def edit_text(self, text, reply_markup=None, **kw):
        self.log.append((text, reply_markup))


class Query:
    def __init__(self, data, log):
        self.data, self.log = data, log
        self.message = SimpleNamespace(chat_id=1)

    async def answer(self, text=None):
        if text:
            self.log.append(("answer:" + text, None))

    async def edit_message_text(self, text, reply_markup=None, **kw):
        self.log.append((text, reply_markup))


def setup(monkeypatch, options=OPTS, hour=10):
    conn = db.connect(":memory:")
    monkeypatch.setattr(bot, "conn", conn)
    monkeypatch.setattr(bot, "now", lambda: datetime(2026, 11, 4, hour, 0, tzinfo=config.TZ))
    form = SimpleNamespace(options=lambda entry: options)
    monkeypatch.setattr(bot, "fetch_form_cached", lambda: form)
    sent = []

    def fake_submit(person, day, option=None):
        sent.append((day, option))
        return SubmitResult(option or "Quarta feira, 04 de novembro", None)
    monkeypatch.setattr(bot, "submit", fake_submit)
    db.upsert_user(conn, 1, nome="Fulano de Tal", telefone="11999999999", email="a@b.c",
                   instagram="", unidade="PD Pinheiros", hora_lembrete="09:00", dias="1")
    log = []
    ctx = SimpleNamespace(chat_data={}, bot=None)
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=1), effective_message=Msg(log), message=Msg(log))
    return conn, log, ctx, update, sent


def labels(kb):
    return [b.text for row in kb.inline_keyboard for b in row]


def click(data, log, ctx):
    asyncio.run(bot.on_vou_choice(SimpleNamespace(callback_query=Query(data, log)), ctx))


def test_pergunta_hoje_ou_outro(monkeypatch):
    conn, log, ctx, update, sent = setup(monkeypatch)
    asyncio.run(bot.cmd_vou(update, ctx))
    text, kb = log[-1]
    assert text == "Para quando?" and labels(kb) == ["Hoje (04/11)", "Outro dia"]

    click("vd:hoje", log, ctx)
    assert sent == [(TODAY, None)]
    assert log[-1][0].startswith("Formulário enviado ✔")


def test_outro_dia_lista_so_futuras(monkeypatch):
    conn, log, ctx, update, sent = setup(monkeypatch)
    asyncio.run(bot.cmd_vou(update, ctx))
    click("vd:outro", log, ctx)
    text, kb = log[-1]
    assert labels(kb) == ["Terça feira, 10 de novembro", "Quinta feira, 12 de novembro"]  # sem passado nem hoje

    click("fut:1", log, ctx)
    assert sent == [(date(2026, 11, 12), "Quinta feira, 12 de novembro")]
    assert db.get_ask(conn, 1, "2026-11-12")["enviado_em"]
    assert "Formulário enviado ✔" in log[-1][0]

    # a data enviada aparece marcada e não é enviada de novo
    asyncio.run(bot.cmd_vou(update, ctx))
    click("vd:outro", log, ctx)
    assert labels(log[-1][1])[1] == "✔ Quinta feira, 12 de novembro"
    click("fut:1", log, ctx)
    assert len(sent) == 1 and log[-1][0].startswith("Já enviei para 12/11 ✔")


def test_futuro_sem_aviso_das_15h(monkeypatch):
    conn, log, ctx, update, sent = setup(monkeypatch, hour=18)
    asyncio.run(bot.cmd_vou(update, ctx))
    click("vd:outro", log, ctx)
    click("fut:0", log, ctx)
    assert "fecha às" not in log[-1][0]


def test_sem_opcao_hoje_vai_direto_para_lista(monkeypatch):
    conn, log, ctx, update, sent = setup(monkeypatch, options=[o for o in OPTS if "04 de" not in o])
    asyncio.run(bot.cmd_vou(update, ctx))
    text, kb = log[-1]
    assert text.startswith("Hoje (04/11) não tem opção no formulário.")
    assert labels(kb) == ["Terça feira, 10 de novembro", "Quinta feira, 12 de novembro"]


def test_sem_datas_futuras(monkeypatch):
    conn, log, ctx, update, sent = setup(monkeypatch, options=OPTS[:2])
    asyncio.run(bot.cmd_vou(update, ctx))
    click("vd:outro", log, ctx)
    assert log[-1] == ("O formulário não tem nenhuma data futura.", None)


def test_lista_expirada(monkeypatch):
    conn, log, ctx, update, sent = setup(monkeypatch)
    click("fut:0", log, ctx)  # sem ter passado pelo /vou (ex.: bot reiniciou)
    assert log[-1][0] == "answer:Essa lista expirou. Mande /vou de novo."
    assert sent == []
