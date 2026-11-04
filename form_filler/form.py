# SPDX-License-Identifier: AGPL-3.0-or-later
"""Leitura e envio do Google Form."""

import argparse
import html
import json
import re
import time as _time
import unicodedata
from dataclasses import dataclass, field
from datetime import date

import httpx

from . import config

MESES = [
    "janeiro", "fevereiro", "marco", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) form-filler/0.1"


class FormError(Exception):
    """Erro que deve ser mostrado ao usuário."""


@dataclass
class Question:
    entry_id: str
    title: str
    required: bool
    options: list[str] = field(default_factory=list)


@dataclass
class Form:
    title: str
    questions: dict[str, Question]  # por entry_id
    hidden: dict[str, str]  # campos ocultos (fbzx, fvv, ...)

    def options(self, entry_id: str) -> list[str]:
        q = self.questions.get(entry_id)
        if q is None:
            raise FormError(f"O formulário mudou: o campo {entry_id} não existe mais.")
        return q.options


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def parse_form(page: str) -> Form:
    m = re.search(r"FB_PUBLIC_LOAD_DATA_ = (.*?);\s*</script>", page, re.S)
    if not m:
        raise FormError("Não consegui ler o formulário (FB_PUBLIC_LOAD_DATA_ ausente).")
    data = json.loads(m.group(1))
    items = data[1][1] or []
    questions: dict[str, Question] = {}
    for item in items:
        title = item[1] or ""
        for sub in item[4] or []:
            entry_id = str(sub[0])
            opts = [o[0] for o in (sub[1] or []) if o and o[0]]
            required = bool(sub[2]) if len(sub) > 2 else False
            questions[entry_id] = Question(entry_id, title, required, opts)
    hidden = {
        html.unescape(n): html.unescape(v)
        for n, v in re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', page)
    }
    title = data[3] if len(data) > 3 and isinstance(data[3], str) else ""
    return Form(title=title, questions=questions, hidden=hidden)


def check_entries(form: Form) -> None:
    expected = [
        config.ENTRY_UNIDADE, config.ENTRY_DATA, config.ENTRY_NOME,
        config.ENTRY_INSTAGRAM, config.ENTRY_TELEFONE,
    ]
    missing = [e for e in expected if e not in form.questions]
    if missing:
        raise FormError(f"O formulário mudou: campos ausentes {missing}.")


def match_date_option(options: list[str], d: date) -> str | None:
    """Acha a opção que corresponde à data, ex.: 'Terça feira, 03 de novembro ...'."""
    mes = MESES[d.month - 1]
    pat = re.compile(rf"(?<!\d)0?{d.day} de {mes}\b")
    for opt in options:
        if pat.search(_norm(opt)):
            return opt
    return None


def fetch_form(client: httpx.Client | None = None) -> Form:
    own = client is None
    client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True)
    try:
        last: Exception | None = None
        for attempt in range(3):
            try:
                r = client.get(config.VIEW_URL)
                r.raise_for_status()
                form = parse_form(r.text)
                check_entries(form)
                return form
            except FormError:
                raise
            except Exception as e:  # rede
                last = e
                _time.sleep(2 ** attempt)
        raise FormError(f"Falha ao baixar o formulário: {last}")
    finally:
        if own:
            client.close()


@dataclass
class Person:
    nome: str
    telefone: str
    email: str
    instagram: str
    unidade: str


def build_payload(form: Form, person: Person, date_option: str) -> dict[str, str]:
    if person.unidade not in form.options(config.ENTRY_UNIDADE):
        raise FormError(f"A unidade '{person.unidade}' não existe mais no formulário. Use /editar.")
    if date_option not in form.options(config.ENTRY_DATA):
        raise FormError("Opção de data inválida.")
    payload = {
        f"entry.{config.ENTRY_UNIDADE}": person.unidade,
        f"entry.{config.ENTRY_DATA}": date_option,
        f"entry.{config.ENTRY_NOME}": person.nome,
        f"entry.{config.ENTRY_INSTAGRAM}": person.instagram or "",
        f"entry.{config.ENTRY_TELEFONE}": person.telefone,
        "emailAddress": person.email,
        f"entry.{config.ENTRY_UNIDADE}_sentinel": "",
        f"entry.{config.ENTRY_DATA}_sentinel": "",
    }
    for k in ("fvv", "pageHistory", "fbzx", "partialResponse", "submissionTimestamp"):
        if k in form.hidden:
            payload[k] = form.hidden[k]
    return payload


CONFIRM_MARKERS = (
    "freebirdFormviewerViewResponseConfirmationMessage",
    "Sua resposta foi registrada",
    "Your response has been recorded",
    "/viewscore",
)


def is_confirmation(status: int, body: str) -> bool:
    if status != 200:
        return False
    if any(m in body for m in CONFIRM_MARKERS):
        return True
    # se voltou a página do form com perguntas, o envio foi rejeitado
    return "FB_PUBLIC_LOAD_DATA_" not in body


def submit(person: Person, d: date) -> str:
    """Envia o formulário para a data. Retorna o texto da opção usada."""
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True) as client:
        form = fetch_form(client)
        option = match_date_option(form.options(config.ENTRY_DATA), d)
        if option is None:
            raise FormError(
                f"O formulário não tem opção para {d.day:02d}/{d.month:02d}. "
                f"Preencha manualmente se necessário: {config.VIEW_URL}"
            )
        payload = build_payload(form, person, option)
        last: Exception | None = None
        for attempt in range(3):
            try:
                r = client.post(config.SUBMIT_URL, data=payload)
            except httpx.HTTPError as e:
                last = e
                _time.sleep(2 ** attempt)
                continue
            if is_confirmation(r.status_code, r.text):
                return option
            raise FormError(f"O Google recusou o envio (HTTP {r.status_code}). Link: {config.VIEW_URL}")
        raise FormError(f"Falha de rede ao enviar: {last}")


def _main() -> None:
    ap = argparse.ArgumentParser(description="Mostra o que seria enviado, sem enviar.")
    ap.add_argument("--dry-run", metavar="AAAA-MM-DD", required=True)
    args = ap.parse_args()
    d = date.fromisoformat(args.dry_run)
    form = fetch_form()
    print("Formulário:", form.title)
    opt = match_date_option(form.options(config.ENTRY_DATA), d)
    print("Opção de data:", opt)
    print("Unidades:", form.options(config.ENTRY_UNIDADE))
    if opt:
        demo = Person("Fulano de Tal", "11999999999", "fulano@example.com", "", form.options(config.ENTRY_UNIDADE)[0])
        print(json.dumps(build_payload(form, demo, opt), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
