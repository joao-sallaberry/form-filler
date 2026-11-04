# SPDX-License-Identifier: AGPL-3.0-or-later
import os
from datetime import datetime

os.environ.setdefault("DB_PATH", ":memory:")

from form_filler import config  # noqa: E402
from form_filler.bot import sent_message  # noqa: E402

OPT = "Terça feira, 10 de novembro"


def at(h, m):
    return datetime(2026, 11, 10, h, m, tzinfo=config.TZ)


def test_antes_das_15():
    msg = sent_message(OPT, at(14, 59))
    assert msg.startswith("Formulário enviado ✔") and "fecha" not in msg


def test_depois_das_15():
    for t in (at(15, 0), at(18, 30)):
        msg = sent_message(OPT, t)
        assert "fecha às 15h" in msg
        assert "Tentei te adicionar" in msg
        assert "pode ser que seu nome não esteja na portaria" in msg
        assert OPT in msg


def test_comandos_e_descricoes():
    from form_filler.bot import COMMANDS, DESCRIPTION, HELP, SHORT_DESCRIPTION
    for c, _, d in COMMANDS:
        assert c.islower() and c.isalnum() and 1 <= len(c) <= 32  # regras do Telegram
        assert 1 <= len(d) <= 256
        assert f"/{c}" in HELP
    assert len(DESCRIPTION) <= 512
    assert len(SHORT_DESCRIPTION) <= 120


def test_aviso_dia_da_semana():
    msg = sent_message("Terça feira, 11 de novembro", datetime(2026, 11, 11, 10, 0, tzinfo=config.TZ), "terça")
    assert "diz terça, mas hoje é quarta" in msg
    assert "ℹ️" not in sent_message(OPT, at(10, 0))
