# SPDX-License-Identifier: AGPL-3.0-or-later
from datetime import date
from pathlib import Path

import pytest

from form_filler import config
import httpx

from form_filler import form as formmod
from form_filler.form import (
    AmbiguousDate, FormError, Person, UncertainSubmit, build_payload, check_entries, choose_option,
    match_date_options, parse_form, submission_status, submit, weekday_mismatch,
)

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
    assert match_date_options(opts, date(2026, 11, 3)) == ["Terça feira, 03 de novembro"]
    assert match_date_options(opts, date(2026, 11, 10)) == ["Terça feira, 10 de novembro"]


def test_match_with_suffix(form):
    [opt] = match_date_options(form.options(config.ENTRY_DATA), date(2026, 10, 27))
    assert opt.startswith("Terça feira, 27 de outubro - Festa")


def test_no_option(form):
    assert match_date_options(form.options(config.ENTRY_DATA), date(2026, 12, 1)) == []


def test_day_not_confused():
    opts = ["Terça feira, 13 de janeiro", "Terça feira, 3 de janeiro"]
    assert match_date_options(opts, date(2027, 1, 3)) == ["Terça feira, 3 de janeiro"]
    assert match_date_options(["Terça feira, 27 de Março"], date(2027, 3, 27)) == ["Terça feira, 27 de Março"]


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


def test_submission_status():
    assert submission_status(200, PAGE) == "rejected"  # o form voltou com as perguntas
    assert submission_status(400, "x") == "rejected"
    assert submission_status(200, '<a href="viewform?usp=form_confirm">Enviar outra resposta</a>') == "ok"
    assert submission_status(200, "<div>Sua resposta foi registrada.</div>") == "ok"
    assert submission_status(200, "<html>página estranha</html>") == "uncertain"
    assert submission_status(500, "erro") == "uncertain"


def test_ambiguous(form):
    form.questions[config.ENTRY_DATA].options.append("Terça feira, 10 de novembro - CANCELADO")
    with pytest.raises(AmbiguousDate) as e:
        choose_option(form, date(2026, 11, 10))
    assert len(e.value.options) == 2
    # com a escolha do usuário, passa
    assert choose_option(form, date(2026, 11, 10), "Terça feira, 10 de novembro - CANCELADO").endswith("CANCELADO")
    # escolha que não é da data de hoje é recusada
    with pytest.raises(FormError):
        choose_option(form, date(2026, 11, 10), "Terça feira, 17 de novembro")


def test_weekday_mismatch():
    assert weekday_mismatch("Terça feira, 10 de novembro", date(2026, 11, 10)) is None  # terça
    assert weekday_mismatch("Terça feira, 11 de novembro", date(2026, 11, 11)) == "terça"  # é quarta
    assert weekday_mismatch("Quarta feira, 11 de novembro", date(2026, 11, 11)) is None
    assert weekday_mismatch("11 de novembro", date(2026, 11, 11)) is None  # sem dia da semana


# ---- envio simulado (sem rede) ----

PERSON = Person("Fulano de Tal", "11999999999", "f@x.com", "", "PD Pinheiros")
DAY = date(2026, 11, 10)


def fake_google(monkeypatch, post_handler):
    calls = {"post": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=PAGE)
        calls["post"] += 1
        return post_handler(request)

    real_client = httpx.Client
    monkeypatch.setattr(formmod.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(formmod._time, "sleep", lambda s: None)
    return calls


def test_submit_ok(monkeypatch):
    calls = fake_google(monkeypatch, lambda r: httpx.Response(200, text='<a href="?usp=form_confirm">outra</a>'))
    result = submit(PERSON, DAY)
    assert result.option == "Terça feira, 10 de novembro" and result.weekday_mismatch is None
    assert calls["post"] == 1


def test_submit_rejected(monkeypatch):
    fake_google(monkeypatch, lambda r: httpx.Response(200, text=PAGE))
    with pytest.raises(FormError) as e:
        submit(PERSON, DAY)
    assert not isinstance(e.value, UncertainSubmit)


def test_submit_uncertain_page(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "x.db"))
    fake_google(monkeypatch, lambda r: httpx.Response(200, text="<html>??</html>"))
    with pytest.raises(UncertainSubmit):
        submit(PERSON, DAY)
    assert (tmp_path / "last_unexpected_response.html").read_text() == "<html>??</html>"


def test_submit_read_timeout_nao_repete(monkeypatch):
    def boom(r):
        raise httpx.ReadTimeout("lento", request=r)
    calls = fake_google(monkeypatch, boom)
    with pytest.raises(UncertainSubmit):
        submit(PERSON, DAY)
    assert calls["post"] == 1  # não tentou de novo


def test_submit_connect_error_repete(monkeypatch):
    state = {"n": 0}

    def flaky(r):
        state["n"] += 1
        if state["n"] < 3:
            raise httpx.ConnectError("sem rede", request=r)
        return httpx.Response(200, text="Sua resposta foi registrada.")
    calls = fake_google(monkeypatch, flaky)
    assert submit(PERSON, DAY).option == "Terça feira, 10 de novembro"
    assert calls["post"] == 3
