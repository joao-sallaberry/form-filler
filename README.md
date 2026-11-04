# form-filler

Bot do Telegram que preenche o formulário do **Espaço Livre do PD Paulista**.

- Cada pessoa se cadastra uma vez (`/start`): nome, telefone, e-mail, Instagram, unidade, dias e horário do lembrete.
- No cadastro a pessoa escolhe receber a pergunta às **terças, às quartas ou nos dois dias** (dá para mudar depois com `/dias`). No horário escolhido, o bot pergunta **Vou / Não vou**.
- Se a resposta for **Vou**, ele baixa o formulário, acha a opção de data de hoje e envia. Se for **Não vou**, ou se não houver resposta, nada é enviado.
- Se o formulário não tiver a data de hoje ou mudar de estrutura, o bot avisa o usuário (e o `ADMIN_CHAT_ID`) em vez de enviar errado.

## Comandos
`/start` `/editar` `/dados` `/horario HH:MM` `/dias` `/vou` `/pausar` `/retomar` `/sair` `/help`

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
