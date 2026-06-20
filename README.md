# Apostas + Crypto — Telegram via GitHub Actions

Bot manual no Telegram, sem servidor 24/7.

## Workflows

| Workflow | Horário | Função |
|----------|---------|--------|
| **Preços Crypto 12h e 18h** | 12:00 e 18:00 (Brasília) | Envia preços + botões |
| **Telegram Poll** | A cada 5 min | Processa cliques (comprar, vender, varredura, apostar) |

## Uso no Telegram

Envie `/start` ao bot e use os botões. Resposta em até ~5 min (intervalo do poll).

## Secrets (GitHub → Settings → Secrets)

- `CONFIG_INI`, `BOT_CONFIG_INI`, `CERT_CRT`, `CERT_KEY` — Betfair
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — Telegram
- `BINANCE_API_KEY`, `BINANCE_SECRET_KEY` — Binance

## Estrutura

```
telegram_bot/     Scripts Telegram + GH Actions
crypto/           API Binance
opportunity_scanner.py
betfair_api.py
api_football.py
config.ini        (local, não commitar)
bot_config.ini    (local, não commitar)
certs/            (local, não commitar)
```
