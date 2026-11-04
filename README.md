# form-filler

Bot do Telegram **não oficial** que preenche o formulário de presença do **Espaço Livre do PD Paulista**.

> ⚠️ Este projeto não é oficial e não tem vínculo com o PD Paulista nem com o Pé Descalço. Ele só preenche, em nome de cada usuário, o formulário público de presença que qualquer pessoa pode preencher à mão.

- Cada pessoa se cadastra uma vez (`/cadastro`): nome, telefone, e-mail, Instagram, unidade, dias e horário do lembrete.
- No cadastro a pessoa escolhe receber a pergunta às **terças, às quartas ou nos dois dias** (dá para mudar depois com `/dias`). No horário escolhido, o bot pergunta **Vou / Não vou**.
- Se a resposta for **Vou**, ele baixa o formulário, acha a opção de data de hoje e envia. Se for **Não vou**, ou se não houver resposta, nada é enviado.
- Se o formulário não tiver a data de hoje ou mudar de estrutura, o bot avisa o usuário (e o `ADMIN_CHAT_ID`) em vez de enviar errado.

## Comandos

| Comando | O que faz |
|---|---|
| `/start` | Mensagem de boas-vindas, enviada pelo Telegram quando alguém abre o bot pela primeira vez. Explica o bot e indica o `/cadastro`; para quem já tem cadastro, mostra a lista de comandos. |
| `/cadastro` | Faz o cadastro, passo a passo: nome completo, telefone, e-mail, Instagram (opcional, `/pular`), unidade, dias (terça, quarta ou os dois) e horário do lembrete (até 14:30). No fim mostra um resumo para confirmar ou refazer. Se a pessoa já tem cadastro, os dados são substituídos. |
| `/cancelar` | Interrompe o cadastro em andamento sem salvar nada. |
| `/pular` | Durante o cadastro, deixa o Instagram em branco. |
| `/dados` | Mostra os dados cadastrados, o horário, os dias e se os lembretes estão ativos ou pausados. |
| `/horario HH:MM` | Muda só o horário do lembrete (ex.: `/horario 10:30`). Aceita até 14:30, porque o formulário precisa ser enviado até as 15h. |
| `/dias` | Mostra botões para marcar ou desmarcar terça e quarta. |
| `/vou` | Envia o formulário de hoje na hora, sem esperar o lembrete. Funciona em qualquer dia que tenha opção no formulário, inclusive aulas remarcadas. Não envia duas vezes no mesmo dia. |
| `/pausar` | Para de mandar os lembretes, mas mantém o cadastro. |
| `/retomar` | Volta a mandar os lembretes. |
| `/sair` | Apaga o cadastro e o histórico de respostas da pessoa. |
| `/help` | Lista os comandos. |

**Lembrete:** no horário escolhido, nos dias marcados (veja abaixo o caso de aula remarcada), o bot pergunta se a pessoa vai, com os botões **✅ Vou** e **❌ Não vou**. "Vou" envia o formulário; se for às 15h ou depois, ele envia mesmo assim e avisa que pode ser que o nome não esteja na portaria. "Não vou" não envia nada.

## Como o bot escolhe a data e confirma o envio
- **Data:** na hora do envio, o bot baixa o formulário e procura a opção que contém a data de hoje (ex.: "10 de novembro"), ignorando acentos e maiúsculas e aceitando texto extra, como "- Festa de Halloween!".
- **Nenhuma opção para hoje:** não envia e manda o link para preencher à mão.
- **Mais de uma opção para hoje** (ex.: "10 de novembro" e "10 de novembro - CANCELADO"): não envia e pergunta ao usuário qual escolher, com botões.
- **Dia da semana divergente** (ex.: "Terça feira, 11 de novembro", sendo que 11/11 é quarta): envia pela data e avisa da divergência.
- **Confirmação:** só considera enviado se o Google devolver a página de confirmação. Se o Google recusar, avisa que não enviou. Se a resposta for inesperada ou a conexão cair no meio do envio, avisa que **não sabe** se registrou, não reenvia sozinho e oferece "Reenviar mesmo assim". A última resposta inesperada fica salva em `data/last_unexpected_response.html`.

## Aulas remarcadas
O formulário é quem diz se há aula no dia. No horário do lembrete, o bot confere se existe uma opção para hoje:

| Situação | O que o bot faz |
|---|---|
| Dia marcado (terça/quarta) com opção no formulário | Pergunta normalmente. |
| Dia marcado **sem** opção no formulário | Não pergunta; avisa que hoje não tem e mostra a próxima data do formulário. |
| Dia fora da rotina (ex.: quinta) **com** opção no formulário | Pergunta a **todos** os usuários ativos, com o aviso "📅 Data extra ou remarcada". O formulário não diz qual aula foi remarcada, por isso vai para todos. |
| Terça/quarta que a pessoa não marcou | Não pergunta. |
| Formulário fora do ar na hora do lembrete | Pergunta nos dias marcados, como antes. |

## Rodar localmente
```bash
cp .env.example .env      # coloque o TELEGRAM_TOKEN do @BotFather
uv sync
uv run pytest
uv run python -m form_filler.form --dry-run 2026-11-10   # mostra o payload, NÃO envia
uv run python -m form_filler.bot
```
Para testar o lembrete fora de terça: `FORCE_WEEKDAY=1` no `.env` (não use em produção).

## Deploy na VPS (systemd)
```bash
sudo useradd -r -m -d /opt/form-filler formfiller
sudo rsync -a --exclude .venv --exclude data ./ /opt/form-filler/
sudo chown -R formfiller: /opt/form-filler
sudo -u formfiller bash -c 'cd /opt/form-filler && uv sync --frozen'
sudo cp deploy/form-filler.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now form-filler
journalctl -u form-filler -f
```
Ajuste o caminho do `uv` no `.service` (`which uv`).

## Privacidade
O banco SQLite (`data/form-filler.db`, permissão 600) guarda os dados pessoais dos usuários. `/sair` apaga tudo do usuário.

## Licença
Copyright (C) 2026 João Victor Henna Sallaberry

Este programa é software livre, distribuído sob a [GNU Affero General Public License v3.0 ou posterior](LICENSE) (AGPL-3.0-or-later). Se você rodar uma versão modificada como serviço acessível a outras pessoas (por exemplo, um bot público), precisa disponibilizar o código-fonte dessa versão aos usuários.
