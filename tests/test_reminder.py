# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio
import os
from datetime import date, datetime
from types import SimpleNamespace

os.environ.setdefault("DB_PATH", ":memory:")

import pytest  # noqa: E402

from form_filler import bot, config, db  # noqa: E402
from form_filler.form import FormError, next_option, option_date  # noqa: E402

TER, QUA, QUI = 1, 2, 3


@pytest.mark.parametrize("dias,wd,has,esperado", [
    ("1", TER, True, "ask"),           # terça marcada, com opção
    ("1", TER, False, "notice"),       # terça marcada, sem opção (remarcada)
    ("1", QUA, True, "skip"),          # quarta normal que a pessoa não marcou
    ("1", QUA, False, "skip"),
    ("1", QUI, True, "ask_extra"),     # quinta com opção: data extra/remarcada
    ("2", QUI, True, "ask_extra"),
    ("1", QUI, False, "skip"),         # quinta comum
    ("1", TER, None, "ask"),           # formulário fora do ar: segue os dias marcados
    ("1", QUI, None, "retry"),
    ("1,2", QUA, True, "ask"),
])
def test_plan_reminder(dias, wd, has, esperado):
    assert bot.plan_reminder(dias, wd, has) == esperado


def test_plan_reminder_force():
    assert bot.plan_reminder("1", QUI, False, force=True) == "notice"


def test_option_date():
    ref = date(2026, 11, 10)
    assert option_date("Quinta feira, 12 de novembro", ref) == date(2026, 11, 12)
    assert option_date("Terça feira, 27 de outubro - Festa!", ref) == date(2026, 10, 27)
    assert option_date("Terça feira, 05 de janeiro", ref) == date(2027, 1, 5)  # virada do ano
    assert option_date("sem data", ref) is None
    assert option_date("31 de fevereiro", ref) is None


def test_next_option():
    opts = ["Terça feira, 03 de novembro", "Quinta feira, 12 de novembro", "Terça feira, 17 de novembro"]
    assert next_option(opts, date(2026, 11, 10)) == (date(2026, 11, 12), "Quinta feira, 12 de novembro")
    assert next_option(opts, date(2026, 11, 17)) is None


# ---- lembrete de ponta a ponta, com bot e formulário falsos ----

class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))


def setup(monkeypatch, weekday_date: date, options: list[str] | Exception):
    conn = db.connect(":memory:")
    monkeypatch.setattr(bot, "conn", conn)
    monkeypatch.setattr(config, "FORCE_WEEKDAY", False)
    monkeypatch.setattr(bot, "now", lambda: datetime.combine(weekday_date, datetime.min.time(), config.TZ).replace(hour=10))

    def fake_form():
        if isinstance(options, Exception):
            raise options
        q = SimpleNamespace(options=options)
        return SimpleNamespace(options=lambda entry: q.options)
    monkeypatch.setattr(bot, "fetch_form_cached", fake_form)
    for chat_id, dias in ((1, "1"), (2, "2"), (3, "1,2")):
        db.upsert_user(conn, chat_id, nome=f"Pessoa {chat_id}", telefone="11999999999", email="a@b.c",
                       instagram="", unidade="PD Pinheiros", hora_lembrete="09:00", dias=dias)
    fb = FakeBot()
    return conn, fb, SimpleNamespace(bot=fb)


def run_tick(ctx):
    asyncio.run(bot.reminder_tick(ctx))


def test_terca_remarcada_para_quinta(monkeypatch):
    opts = ["Quarta feira, 11 de novembro", "Quinta feira, 12 de novembro"]
    # terça 10/11: sem opção -> quem marcou terça recebe aviso, sem botões
    conn, fb, ctx = setup(monkeypatch, date(2026, 11, 10), opts)
    run_tick(ctx)
    by_chat = {c: (t, kb) for c, t, kb in fb.sent}
    assert set(by_chat) == {1, 3}
    for c in (1, 3):
        t, kb = by_chat[c]
        assert kb is None and "não tem Espaço Livre" in t and "Quarta feira, 11 de novembro" in t
    run_tick(ctx)  # minuto seguinte: nada repetido
    assert len(fb.sent) == 2

    # quinta 12/11: data extra -> todos são perguntados
    conn, fb, ctx = setup(monkeypatch, date(2026, 11, 12), opts)
    run_tick(ctx)
    assert sorted(c for c, _, _ in fb.sent) == [1, 2, 3]
    for _, t, kb in fb.sent:
        assert t.startswith("📅 Data extra ou remarcada: Quinta feira, 12 de novembro") and kb is not None


def test_quarta_normal(monkeypatch):
    conn, fb, ctx = setup(monkeypatch, date(2026, 11, 11), ["Quarta feira, 11 de novembro"])
    run_tick(ctx)
    assert sorted(c for c, _, _ in fb.sent) == [2, 3]
    assert all("📅" not in t for _, t, _ in fb.sent)


def test_formulario_fora_do_ar(monkeypatch):
    conn, fb, ctx = setup(monkeypatch, date(2026, 11, 10), FormError("fora do ar"))
    run_tick(ctx)
    assert sorted(c for c, _, _ in fb.sent) == [1, 3]  # segue os dias marcados
    assert all(kb is not None for _, _, kb in fb.sent)
