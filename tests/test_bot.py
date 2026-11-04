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
        assert "talvez seu nome não esteja na lista" in msg
        assert OPT in msg
