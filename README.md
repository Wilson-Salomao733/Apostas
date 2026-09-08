# Apostas — Bot Docker standalone

Bot de apostas Betfair com Telegram, modos manual / semi-auto / full-auto.

## Subir com Docker

```bash
cp .env.example .env   # preencha TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
docker compose up -d --build
docker compose logs -f
```

## Modos (Telegram)

| Modo | Comportamento |
|------|---------------|
| **Manual** | Varredura só ao clicar em Varredura |
| **Semi-auto** | Varre a cada `check_interval` e envia botão Apostar |
| **Full auto** | Aposta sozinho quando IA + limites aprovam |
| **Parar** | Desliga o loop automático |

Troque o modo pelos botões no Telegram (`/start`).

## Estratégias (Telegram)

| Estratégia | Tipo |
|------------|------|
| **U4.5+U10.5** (`combo_u45_u105`) | Múltipla no mesmo jogo; se faltar mercado de escanteios, fallback para só Under 4.5 |
| **Só U4.5 gols** (`under45`) | Simples |
| **Só U10.5 esc** (`corners_105`) | Simples |

Padrão: `combo_u45_u105`.

## Configuração

| Arquivo | Função |
|---------|--------|
| `config.ini` | Credenciais Betfair + certs |
| `bot_config.ini` | Estratégias, stakes, limites, chaves API |
| `data/bot_mode.json` | Modo atual (manual/semi/auto/off) |
| `data/enabled_sports.json` | Esportes ativos (football, tennis) |

## Backtest (CSVs liquidados)

```bash
python backtest/settled_csv.py
python backtest/settled_csv.py "ExchangeBets_Settled (39).csv"
```

## Local (sem Docker)

```bash
pip install -r requirements.txt
python betting_bot.py
```

## Estrutura

```
betting_bot.py       Entry point (Telegram + worker)
auto_worker.py       Loop automático semi/full
config_loader.py     Lê bot_config.ini e modos
risk_manager.py      Limites diários e apostas ativas
opportunity_scanner.py  Varredura futebol + tênis
backtest/settled_csv.py Análise de histórico CSV
```

> Betfair bloqueia servidores nos EUA — rode no Brasil ou VPS fora dos EUA.
