# Apostas + Crypto

## Bot Telegram (resposta instantânea)

Rode o **hub** no seu PC — processa botões na hora (crypto + apostas + Betfair).

```bash
cd ../hub
./run.sh start      # background
./run.sh status
./run.sh stop
```

Ou com Docker:

```bash
cd ../hub
docker compose up -d
docker compose logs -f
```

## GitHub Actions (só lembrete de preços)

| Workflow | Horário | Função |
|----------|---------|--------|
| **Preços Crypto 12h e 18h** | 12:00 e 18:00 (Brasília) | Envia cotações automáticas |

> Apostas e cliques nos botões **não** usam GitHub Actions (Betfair bloqueia servidores EUA).

## Secrets (GitHub)

- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `BINANCE_*` — preços automáticos
- `CONFIG_INI`, `BOT_CONFIG_INI`, `CERT_*` — legado (hub local usa arquivos em `config.ini`)

## Estrutura

```
hub/              Bot Telegram local (use este)
telegram_bot/     Scripts usados pelo cron de preços
crypto/           API Binance
opportunity_scanner.py
betfair_api.py
config.ini        (local, não commitar)
bot_config.ini    (local, não commitar)
certs/            (local, não commitar)
```
