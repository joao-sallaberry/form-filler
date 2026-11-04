# SPDX-License-Identifier: AGPL-3.0-or-later
from datetime import date
from pathlib import Path

import pytest

from form_filler import config
from form_filler.form import FormError, Person, build_payload, is_confirmation, match_date_option, parse_form, check_entries

PAGE = (Path(__file__).parent / "fixtures" / "viewform.html").read_text()


@pytest.fixture
def form():
    return parse_form(PAGE)


def test_parse(form):
    check_entries(form)
    assert "PD Pinheiros" in form.options(config.ENTRY_UNIDADE)
    assert len(form.options(config.ENTRY_DATA)) == 12
    assert form.hidden["fvv"] == "1"
    assert "fbzx" in form.hidden


def test_match_simple(form):
    opts = form.options(config.ENTRY_DATA)
    assert match_date_option(opts, date(2026, 11, 3)) == "Terça feira, 03 de novembro"
    assert match_date_option(opts, date(2026, 11, 10)) == "Terça feira, 10 de novembro"


def test_match_with_suffix(form):
    opt = match_date_option(form.options(config.ENTRY_DATA), date(2026, 10, 27))
    assert opt.startswith("Terça feira, 27 de outubro - Festa")


def test_no_option(form):
    assert match_date_option(form.options(config.ENTRY_DATA), date(2026, 12, 1)) is None


def test_day_not_confused():
    opts = ["Terça feira, 13 de janeiro", "Terça feira, 3 de janeiro"]
    assert match_date_option(opts, date(2027, 1, 3)) == "Terça feira, 3 de janeiro"
    assert match_date_option(["Terça feira, 27 de Março"], date(2027, 3, 27)) == "Terça feira, 27 de Março"


def test_payload(form):
    p = Person("Fulano de Tal", "11999999999", "f@x.com", "", "PD Pinheiros")
    payload = build_payload(form, p, "Terça feira, 10 de novembro")
    assert payload["entry.1370842096"] == "PD Pinheiros"
    assert payload["entry.204293368"] == "Terça feira, 10 de novembro"
    assert payload["entry.1120590305"] == "Fulano de Tal"
    assert payload["entry.730700876"] == "11999999999"
    assert payload["emailAddress"] == "f@x.com"
    assert payload["fvv"] == "1"


def test_payload_bad_unidade(form):
    with pytest.raises(FormError):
        build_payload(form, Person("A B", "1", "a@b.c", "", "PD Marte"), "Terça feira, 10 de novembro")


def test_confirmation():
    assert not is_confirmation(200, PAGE)
    assert not is_confirmation(400, "x")
    assert is_confirmation(200, "<div>Sua resposta foi registrada.</div>")
