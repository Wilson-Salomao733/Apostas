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
| **Full auto** | Aposta quando modelo determinístico, EV e limites aprovam |
| **Parar** | Desliga o loop automático |

Troque o modo pelos botões no Telegram (`/start`).

## Estratégias (Telegram)

| Estratégia | Tipo |
|------------|------|
| **U10.5 e U4.5 indep.** (`combo_u105_u45`) | Duas pernas no mesmo ciclo, sem casar no mesmo jogo |
| **U4.5+U10.5** (`combo_u45_u105`) | Carteira antiga de duas ordens no mesmo evento |
| **Só U4.5 gols** (`under45`) | Simples 1.30–1.40, só ligas com Over 2.5 ≤ 50% |
| **Só U10.5 esc** (`corners_105`) | Simples 1.40–1.73, spread máximo 10% |

Padrão: `combo_u105_u45`, stakes iniciais de R$20 por perna. Ajuste pelo menu
**Valores** ou por `/stake_corners VALOR` e `/stake_goals VALOR` (R$2–R$35).
Valores acima de R$10 exigem confirmação. U10.5 entra pela faixa de preço e
spread da Betfair, sem estatística de escanteios. U4.5 exige liga da allowlist
e favorito de `MATCH_ODDS` ≥ 1.40. O Groq não autoriza apostas.

A allowlist de U4.5 começa no Brasileirão Série A (50% Over 2.5) e desce
pelas ligas que a Betfair já listou no catálogo ou nos CSVs liquidados
(Série B, La Liga 2, Argentina, Egito, Grécia, etc.). Copas, feminino e
Champions ficam de fora desta perna.

### Liquidez e risco

- `totalMatched=0` não elimina um mercado se existir oferta BACK executável.
- São exigidos status OPEN, runner ACTIVE, tamanho mínimo e spread máximo.
- A comissão padrão da Betfair Brasil é modelada como 6,5%.
- Na estratégia principal, a perda diária e a exposição total máximas são R$70.
- O fallback U4.5 da carteira começa desativado.

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
python backtest/settled_csv.py --json
```

O backtest deduplica `betId`, calcula ROI, drawdown, intervalo de confiança e
teste temporal. Para gerar o mapa sanitizado de campos recebidos da Betfair:

```bash
python betfair_inventory.py
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
strategy_model.py    Liquidez, probabilidade de equilíbrio e EV
bet_ledger.py        Snapshots, ordens, pernas e liquidações em SQLite
opportunity_scanner.py  Varredura futebol + tênis
backtest/settled_csv.py Análise de histórico CSV
```

> Betfair bloqueia servidores nos EUA — rode no Brasil ou VPS fora dos EUA.
