# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lista os usuários cadastrados no banco.

Uso: uv run python -m form_filler.usuarios
"""
from . import db
from .bot import dias_label

COLUNAS = [
    ("chat_id", "chat_id"),
    ("nome", "nome"),
    ("telefone", "telefone"),
    ("email", "e-mail"),
    ("instagram", "instagram"),
    ("unidade", "unidade"),
    ("hora_lembrete", "hora"),
    ("dias", "dias"),
    ("ativo", "status"),
    ("criado_em", "criado em"),
]


def linhas(conn) -> list[list[str]]:
    rows = conn.execute("SELECT * FROM users ORDER BY criado_em").fetchall()
    out = []
    for r in rows:
        valores = {k: str(r[k]) for k, _ in COLUNAS}
        valores["dias"] = dias_label(r["dias"])
        valores["ativo"] = "ativo" if r["ativo"] else "pausado"
        valores["criado_em"] = r["criado_em"][:10]  # só AAAA-MM-DD
        out.append([valores[k] for k, _ in COLUNAS])
    return out


def formatar(rows: list[list[str]]) -> str:
    if not rows:
        return "Nenhum usuário cadastrado."
    tabela = [[titulo for _, titulo in COLUNAS], *rows]
    larguras = [max(len(linha[i]) for linha in tabela) for i in range(len(COLUNAS))]
    texto = ["  ".join(c.ljust(w) for c, w in zip(linha, larguras)).rstrip() for linha in tabela]
    texto.insert(1, "  ".join("-" * w for w in larguras))
    ativos = sum(1 for r in rows if r[COLUNAS.index(("ativo", "status"))] == "ativo")
    texto.append(f"\n{len(rows)} usuário(s), {ativos} ativo(s).")
    return "\n".join(texto)


def main() -> None:
    print(formatar(linhas(db.connect())))


if __name__ == "__main__":
    main()
