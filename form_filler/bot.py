# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bot do Telegram: cadastro, lembrete semanal e envio do formulário."""

import asyncio
import logging
import re
from collections import defaultdict
from datetime import date, datetime

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from . import config, db
from .form import (
    DIAS_SEMANA, AmbiguousDate, FormError, Person, UncertainSubmit, fetch_form, fetch_form_cached,
    match_date_options, next_option, submit,
)

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("form-filler")

NOME, TELEFONE, EMAIL, INSTAGRAM, UNIDADE, DIAS, HORA, CONFIRMA = range(8)

# opções do cadastro: (valor da coluna dias, rótulo do botão)
DIAS_OPCOES = [("1", "Terça"), ("2", "Quarta"), ("1,2", "Terça e quarta")]

conn = db.connect()
_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

# Fonte única dos comandos: alimenta o /help e o menu "/" do Telegram.
# (comando, argumentos mostrados no /help, descrição)
COMMANDS = [
    ("cadastro", "", "fazer ou refazer o cadastro"),
    ("dados", "", "ver seus dados"),
    ("horario", " HH:MM", "mudar o horário do lembrete"),
    ("dias", "", "escolher os dias (terça/quarta)"),
    ("vou", "", "enviar o formulário de hoje agora"),
    ("pausar", "", "parar os lembretes"),
    ("retomar", "", "voltar os lembretes"),
    ("sair", "", "apagar seus dados"),
    ("help", "", "mostrar a lista de comandos"),
]

HELP = "Comandos:\n" + "\n".join(f"/{c}{a} – {d}" for c, a, d in COMMANDS)

INTRO = (
    "⚠️ Bot NÃO OFICIAL, sem vínculo com o PD Paulista.\n\n"
    "Oi! Eu preencho por você o formulário de presença do Espaço Livre do PD Paulista.\n"
    "Nos dias que você escolher (terça, quarta ou os dois) eu pergunto se você vai; "
    "se responder ✅ Vou, eu envio o formulário."
)

# chat vazio, antes de "Iniciar" (até 512 caracteres)
DESCRIPTION = (
    INTRO + "\n\nPara começar, aperte Iniciar e depois mande /cadastro. "
    "O formulário precisa chegar até as 15h do dia."
)
# perfil do bot e link compartilhado (até 120 caracteres)
SHORT_DESCRIPTION = "Bot não oficial que preenche por você o formulário de presença do Espaço Livre do PD Paulista."


def now() -> datetime:
    return datetime.now(config.TZ)


def parse_hhmm(text: str) -> str | None:
    m = re.fullmatch(r"\s*(\d{1,2})[:h](\d{2})\s*", text)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    hhmm = f"{h:02d}:{mi:02d}"
    if hhmm > config.LATEST_REMINDER.strftime("%H:%M"):
        return None
    return hhmm


def dias_label(dias: str) -> str:
    nomes = [config.EVENT_WEEKDAYS[int(d)] for d in dias.split(",") if d and int(d) in config.EVENT_WEEKDAYS]
    return " e ".join(nomes) or "nenhum"


def person_from(row) -> Person:
    return Person(row["nome"], row["telefone"], row["email"], row["instagram"], row["unidade"])


# ---------- cadastro ----------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Primeira mensagem do Telegram: só apresenta o bot."""
    if db.get_user(conn, update.effective_chat.id):
        await update.message.reply_text(f"{INTRO}\n\nVocê já tem cadastro.\n\n{HELP}")
    else:
        await update.message.reply_text(f"{INTRO}\n\nPara começar, mande /cadastro.")


async def cadastro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "Vamos ao cadastro (/cancelar para sair).\nQual o seu *nome completo*?",
        parse_mode="Markdown",
    )
    return NOME


async def got_nome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    nome = update.message.text.strip()
    if len(nome.split()) < 2:
        await update.message.reply_text("Manda o nome completo, por favor (nome e sobrenome).")
        return NOME
    context.user_data["nome"] = nome
    await update.message.reply_text("Seu WhatsApp ou telefone (com DDD)?")
    return TELEFONE


async def got_telefone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    digits = re.sub(r"\D", "", update.message.text)
    if not 10 <= len(digits) <= 13:
        await update.message.reply_text("Não parece um telefone válido. Ex.: 11999998888")
        return TELEFONE
    context.user_data["telefone"] = digits
    await update.message.reply_text("Seu e-mail?")
    return EMAIL


async def got_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    email = update.message.text.strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        await update.message.reply_text("E-mail inválido, tenta de novo.")
        return EMAIL
    context.user_data["email"] = email
    await update.message.reply_text("Seu Instagram? (ou /pular)")
    return INSTAGRAM


async def got_instagram(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    context.user_data["instagram"] = "" if text == "/pular" else text
    try:
        form = await asyncio.to_thread(fetch_form)
        unidades = form.options(config.ENTRY_UNIDADE)
    except FormError as e:
        await update.message.reply_text(f"Não consegui ler o formulário agora: {e}\nTente /cadastro mais tarde.")
        return ConversationHandler.END
    context.user_data["unidades"] = unidades
    kb = [[InlineKeyboardButton(u, callback_data=f"u:{i}")] for i, u in enumerate(unidades)]
    await update.message.reply_text("Qual unidade você é?", reply_markup=InlineKeyboardMarkup(kb))
    return UNIDADE


async def got_unidade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    unidade = context.user_data["unidades"][int(q.data.split(":")[1])]
    context.user_data["unidade"] = unidade
    await q.edit_message_text(f"Unidade: {unidade}")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(label, callback_data=f"d:{dias}") for dias, label in DIAS_OPCOES
    ]])
    await q.message.reply_text("Em quais dias você quer receber a pergunta?", reply_markup=kb)
    return DIAS


async def got_dias(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    dias = q.data.split(":", 1)[1]
    context.user_data["dias"] = dias
    await q.edit_message_text(f"Dias: {dias_label(dias)}")
    await q.message.reply_text(
        "Que horas você quer receber a pergunta? (ex. 09:00). "
        f"O formulário precisa ser enviado até as {config.DEADLINE:%H}h."
    )
    return HORA


async def got_hora(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    hhmm = parse_hhmm(update.message.text)
    if not hhmm:
        await update.message.reply_text(f"Horário inválido. Use HH:MM até {config.LATEST_REMINDER:%H:%M}, ex.: 10:00")
        return HORA
    context.user_data["hora_lembrete"] = hhmm
    u = context.user_data
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirmar", callback_data="cad:ok"),
        InlineKeyboardButton("✏️ Refazer", callback_data="cad:redo"),
    ]])
    await update.message.reply_text(
        f"Confere?\n\nNome: {u['nome']}\nTelefone: {u['telefone']}\nE-mail: {u['email']}\n"
        f"Instagram: {u['instagram'] or '-'}\nUnidade: {u['unidade']}\n"
        f"Lembrete: {hhmm} ({dias_label(u['dias'])})",
        reply_markup=kb,
    )
    return CONFIRMA


async def got_confirma(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    if q.data == "cad:redo":
        await q.edit_message_text("Ok, vamos de novo. Qual o seu nome completo?")
        return NOME
    u = context.user_data
    db.upsert_user(
        conn, q.message.chat_id,
        nome=u["nome"], telefone=u["telefone"], email=u["email"],
        instagram=u["instagram"], unidade=u["unidade"], hora_lembrete=u["hora_lembrete"], dias=u["dias"],
    )
    row = db.get_user(conn, q.message.chat_id)
    await q.edit_message_text(
        f"Cadastro salvo! Vou te perguntar às {row['hora_lembrete']} ({dias_label(row['dias'])}).\n\n{HELP}"
    )
    context.user_data.clear()
    return ConversationHandler.END


async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Cadastro cancelado.")
    return ConversationHandler.END


# ---------- comandos ----------

async def require_user(update: Update):
    row = db.get_user(conn, update.effective_chat.id)
    if row is None:
        await update.effective_message.reply_text("Você ainda não tem cadastro. Use /cadastro.")
    return row


async def cmd_dados(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not (row := await require_user(update)):
        return
    await update.message.reply_text(
        f"Nome: {row['nome']}\nTelefone: {row['telefone']}\nE-mail: {row['email']}\n"
        f"Instagram: {row['instagram'] or '-'}\nUnidade: {row['unidade']}\n"
        f"Lembrete: {row['hora_lembrete']} ({dias_label(row['dias'])})\n"
        f"Status: {'ativo' if row['ativo'] else 'pausado'}"
    )


async def cmd_horario(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_user(update):
        return
    hhmm = parse_hhmm(" ".join(context.args)) if context.args else None
    if not hhmm:
        await update.message.reply_text(f"Uso: /horario HH:MM (até {config.LATEST_REMINDER:%H:%M})")
        return
    db.set_field(conn, update.effective_chat.id, "hora_lembrete", hhmm)
    await update.message.reply_text(f"Lembrete agora às {hhmm}.")


def dias_keyboard(dias: str) -> InlineKeyboardMarkup:
    sel = set(dias.split(","))
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(("✅ " if str(wd) in sel else "⬜ ") + nome, callback_data=f"dia:{wd}")
        for wd, nome in config.EVENT_WEEKDAYS.items()
    ]])


async def cmd_dias(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not (row := await require_user(update)):
        return
    await update.message.reply_text("Em quais dias quer ser perguntado?", reply_markup=dias_keyboard(row["dias"]))


async def on_dia(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    row = db.get_user(conn, q.message.chat_id)
    if row is None:
        await q.answer("Sem cadastro. Use /cadastro.")
        return
    wd = q.data.split(":")[1]
    sel = {d for d in row["dias"].split(",") if d}
    sel ^= {wd}
    dias = ",".join(sorted(sel))
    db.set_field(conn, q.message.chat_id, "dias", dias)
    await q.answer(f"Dias: {dias_label(dias)}")
    await q.edit_message_reply_markup(dias_keyboard(dias))


async def cmd_pausar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await require_user(update):
        db.set_field(conn, update.effective_chat.id, "ativo", 0)
        await update.message.reply_text("Lembretes pausados. /retomar para voltar.")


async def cmd_retomar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await require_user(update):
        db.set_field(conn, update.effective_chat.id, "ativo", 1)
        await update.message.reply_text("Lembretes retomados.")


async def cmd_sair(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db.delete_user(conn, update.effective_chat.id)
    await update.message.reply_text("Seus dados foram apagados. Até mais!")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP)


# ---------- envio ----------

Reply = tuple[str, InlineKeyboardMarkup | None]


async def do_submit(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, day: date,
    option: str | None = None, force: bool = False,
) -> Reply:
    """Envia o form (idempotente). Retorna a mensagem e, se for o caso, botões."""
    answered_at = now()
    async with _locks[chat_id]:
        iso = day.isoformat()
        ask = db.get_ask(conn, chat_id, iso)
        if ask and ask["enviado_em"]:
            return f"Já enviei hoje ✔ ({ask['opcao']})", None
        if ask and ask["resposta"] == "incerto" and not force:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Reenviar mesmo assim", callback_data=f"force:{iso}")]])
            return (
                "⚠️ Já tentei enviar hoje, mas não consegui confirmar se o Google registrou. "
                "Reenviar pode criar uma resposta duplicada.", kb,
            )
        row = db.get_user(conn, chat_id)
        if row is None:
            return "Você não tem cadastro. Use /cadastro.", None
        try:
            result = await asyncio.to_thread(submit, person_from(row), day, option)
        except AmbiguousDate as e:
            context.chat_data.setdefault("opcoes", {})[iso] = e.options
            lista = "\n".join(f"{i}. {o}" for i, o in enumerate(e.options, 1))
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton(str(i), callback_data=f"opt:{iso}:{i - 1}") for i in range(1, len(e.options) + 1)],
                 [InlineKeyboardButton("❌ Não vou", callback_data=f"nao:{iso}")]]
            )
            return f"O formulário tem mais de uma opção para hoje. Qual delas?\n\n{lista}", kb
        except UncertainSubmit as e:
            db.record_answer(conn, chat_id, iso, "incerto", erro=str(e))
            await alert_admin(context, f"Envio incerto de {chat_id}: {e}")
            return f"⚠️ {e}", None
        except FormError as e:
            db.record_answer(conn, chat_id, iso, "sim", erro=str(e))
            await alert_admin(context, f"Falha no envio de {chat_id}: {e}")
            return f"❗ Não consegui enviar: {e}", None
        except Exception as e:  # noqa: BLE001
            log.exception("erro inesperado no envio (chat %s)", chat_id)
            db.record_answer(conn, chat_id, iso, "sim", erro=repr(e))
            await alert_admin(context, f"Erro inesperado no envio de {chat_id}: {e!r}")
            return f"❗ Erro inesperado. Preencha manualmente: {config.VIEW_URL}", None
        db.record_answer(conn, chat_id, iso, "sim", opcao=result.option, enviado=True)
        log.info("formulário enviado (chat %s, %s)", chat_id, iso)
        return sent_message(result.option, answered_at, result.weekday_mismatch), None


def sent_message(option: str, answered_at: datetime, weekday_mismatch: str | None = None) -> str:
    if answered_at.time() >= config.DEADLINE:
        msg = (
            f"⚠️ A lista da portaria fecha às {config.DEADLINE:%H}h. "
            "Tentei te adicionar mesmo assim, mas pode ser que seu nome não esteja na portaria.\n\n"
            f"Formulário enviado:\n{option}"
        )
    else:
        msg = f"Formulário enviado ✔\n{option}"
    if weekday_mismatch:
        hoje = DIAS_SEMANA[answered_at.weekday()]
        msg += (
            f"\n\nℹ️ A opção do formulário diz {weekday_mismatch}, mas hoje é {hoje}. "
            "Enviei pela data; pode ser um erro de digitação no formulário."
        )
    return msg


async def alert_admin(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    if config.ADMIN_CHAT_ID:
        try:
            await context.bot.send_message(config.ADMIN_CHAT_ID, text)
        except Exception:  # noqa: BLE001
            log.exception("falha ao alertar admin")


async def on_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Botões: vou:<data>, nao:<data>, opt:<data>:<i> (escolha de opção), force:<data> (reenviar)."""
    q = update.callback_query
    action, iso, *rest = q.data.split(":")
    day = date.fromisoformat(iso)
    chat_id = q.message.chat_id
    if day != now().date():
        await q.answer("Essa pergunta é de outro dia.")
        return
    if action == "nao":
        ask = db.get_ask(conn, chat_id, iso)
        if ask and ask["enviado_em"]:
            await q.answer("O formulário já foi enviado hoje.")
            return
        db.record_answer(conn, chat_id, iso, "nao")
        await q.answer()
        await q.edit_message_text("Beleza, não vou enviar hoje. 👋")
        return
    option = None
    if action == "opt":
        opcoes = context.chat_data.get("opcoes", {}).get(iso) or []
        i = int(rest[0])
        if not 0 <= i < len(opcoes):  # o bot reiniciou e perdeu a lista
            await q.answer("Essa escolha expirou. Mande /vou de novo.")
            return
        option = opcoes[i]
    await q.answer("Enviando…")
    await q.edit_message_text("Enviando o formulário…")
    text, kb = await do_submit(context, chat_id, day, option=option, force=action == "force")
    await q.edit_message_text(text, reply_markup=kb)


async def cmd_vou(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not (row := await require_user(update)):
        return
    today = now().date()
    # vale qualquer dia que tenha opção no formulário (inclusive aulas remarcadas)
    msg = await update.message.reply_text("Enviando o formulário…")
    text, kb = await do_submit(context, row["chat_id"], today)
    await msg.edit_text(text, reply_markup=kb)


def plan_reminder(dias: str, weekday: int, has_today: bool | None, force: bool = False) -> str:
    """Decide o lembrete de um usuário hoje.

    has_today: o formulário tem opção para hoje? (None = não consegui ler o formulário)
    Retorna 'ask', 'ask_extra' (data fora da rotina), 'notice' (dia marcado sem opção),
    'skip' ou 'retry' (tentar no próximo minuto).
    """
    marcado = force or str(weekday) in dias.split(",")
    if has_today is None:
        return "ask" if marcado else "retry"
    if has_today:
        if marcado:
            return "ask"
        # terça/quarta que a pessoa não marcou: aula normal que ela não quer
        return "skip" if weekday in config.EVENT_WEEKDAYS else "ask_extra"
    return "notice" if marcado else "skip"


def answer_keyboard(day: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Vou", callback_data=f"vou:{day}"),
        InlineKeyboardButton("❌ Não vou", callback_data=f"nao:{day}"),
    ]])


def notice_message(today: date, options: list[str]) -> str:
    msg = f"Hoje ({today:%d/%m}) não tem Espaço Livre no formulário. Pode ter sido remarcado."
    if nxt := next_option(options, today):
        msg += f"\nPróxima data no formulário: {nxt[1]}"
    return msg + "\n\nSe a data de hoje aparecer depois, mande /vou."


async def reminder_tick(context: ContextTypes.DEFAULT_TYPE) -> None:
    t = now()
    today = t.date()
    day = today.isoformat()
    rows = db.due_users(conn, day, t.strftime("%H:%M"))
    if not rows:
        return
    try:
        form = await asyncio.to_thread(fetch_form_cached)
        options = form.options(config.ENTRY_DATA)
        today_opts = match_date_options(options, today)
        has_today = bool(today_opts)
    except FormError as e:
        log.warning("lembrete sem formulário (%s); usando os dias marcados", e)
        options, today_opts, has_today = [], [], None

    for row in rows:
        chat_id = row["chat_id"]
        acao = plan_reminder(row["dias"], today.weekday(), has_today, config.FORCE_WEEKDAY)
        if acao == "retry":
            continue
        if acao == "skip":
            db.mark_skipped(conn, chat_id, day, "fora_dos_dias")
            continue
        nome = row["nome"].split()[0]
        if acao == "notice":
            db.mark_skipped(conn, chat_id, day, "sem_opcao")
            text, kb = notice_message(today, options), None
        else:
            db.mark_asked(conn, chat_id, day)  # antes de enviar: evita duplicar
            text = f"Oi, {nome}! Você vai ao Espaço Livre hoje ({t:%d/%m})?"
            if acao == "ask_extra":
                text = "📅 Data extra ou remarcada: " + " / ".join(today_opts) + "\n\n" + text
            kb = answer_keyboard(day)
        try:
            await context.bot.send_message(chat_id, text, reply_markup=kb)
        except Exception:  # noqa: BLE001 (ex.: usuário bloqueou o bot)
            log.exception("falha ao enviar lembrete para %s", chat_id)


async def setup_bot_profile(app: Application) -> None:
    """Registra o menu de comandos e as descrições do bot no Telegram."""
    try:
        await app.bot.set_my_commands([BotCommand(c, d) for c, _, d in COMMANDS])
        await app.bot.set_my_description(DESCRIPTION)
        await app.bot.set_my_short_description(SHORT_DESCRIPTION)
        log.info("menu de comandos e descrições atualizados")
    except Exception:  # noqa: BLE001 (não impede o bot de rodar)
        log.exception("falha ao atualizar menu/descrições do bot")


def main() -> None:
    if not config.TELEGRAM_TOKEN:
        raise SystemExit("Defina TELEGRAM_TOKEN no .env")
    app = Application.builder().token(config.TELEGRAM_TOKEN).post_init(setup_bot_profile).build()

    text = filters.TEXT & ~filters.COMMAND
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("cadastro", cadastro)],
        states={
            NOME: [MessageHandler(text, got_nome)],
            TELEFONE: [MessageHandler(text, got_telefone)],
            EMAIL: [MessageHandler(text, got_email)],
            INSTAGRAM: [MessageHandler(text, got_instagram), CommandHandler("pular", got_instagram)],
            UNIDADE: [CallbackQueryHandler(got_unidade, pattern=r"^u:\d+$")],
            DIAS: [CallbackQueryHandler(got_dias, pattern=r"^d:[12](,2)?$")],
            HORA: [MessageHandler(text, got_hora)],
            CONFIRMA: [CallbackQueryHandler(got_confirma, pattern=r"^cad:")],
        },
        fallbacks=[CommandHandler("cancelar", cancelar), CommandHandler("cadastro", cadastro)],
    ))
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("dados", cmd_dados))
    app.add_handler(CommandHandler("horario", cmd_horario))
    app.add_handler(CommandHandler("dias", cmd_dias))
    app.add_handler(CommandHandler("vou", cmd_vou))
    app.add_handler(CommandHandler("pausar", cmd_pausar))
    app.add_handler(CommandHandler("retomar", cmd_retomar))
    app.add_handler(CommandHandler("sair", cmd_sair))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CallbackQueryHandler(on_dia, pattern=r"^dia:\d$"))
    app.add_handler(CallbackQueryHandler(on_answer, pattern=r"^((vou|nao|force):\d{4}-\d{2}-\d{2}|opt:\d{4}-\d{2}-\d{2}:\d+)$"))

    app.job_queue.run_repeating(reminder_tick, interval=60, first=5)
    log.info("bot iniciado")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
