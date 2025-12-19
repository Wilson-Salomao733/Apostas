# 💾 Sistema de Banco de Dados - Bot Betfair

## 📋 Visão Geral

O bot agora usa um **banco de dados SQLite** para armazenar todas as apostas e resultados, ao invés de manter tudo na memória ou em arquivos JSON.

### ✅ Vantagens

- ✅ **Persistência garantida**: Dados nunca são perdidos
- ✅ **Histórico completo**: Todas as apostas são salvas permanentemente
- ✅ **Consultas rápidas**: SQLite é otimizado para buscas
- ✅ **Estatísticas avançadas**: Geração automática de relatórios diários
- ✅ **Backup fácil**: Basta copiar o arquivo `data/bets.db`
- ✅ **Escalável**: Suporta milhares de apostas sem lentidão

## 🗄️ Estrutura do Banco

### Tabela: `bets`
Armazena todas as apostas (ativas e fechadas)

| Campo | Tipo | Descrição |
|-------|------|-----------|
| bet_id | TEXT | ID único da aposta (PK) |
| market_id | TEXT | ID do mercado Betfair |
| event_id | TEXT | ID do evento |
| event_name | TEXT | Nome do evento (ex: "Brasil vs Argentina") |
| sport | TEXT | Esporte (SOCCER, TENNIS, ICE_HOCKEY) |
| strategy | TEXT | Estratégia usada |
| side | TEXT | BACK ou LAY |
| selection_id | TEXT | ID da seleção apostada |
| entry_price | REAL | Odd de entrada |
| entry_time | TIMESTAMP | Momento da aposta |
| stake | REAL | Valor apostado |
| liability | REAL | Responsabilidade (para LAY) |
| take_profit_pct | REAL | % de take profit |
| stop_loss_pct | REAL | % de stop loss |
| status | TEXT | ACTIVE, CLOSED_PROFIT, CLOSED_LOSS, CLOSED_TIMEOUT |
| current_price | REAL | Odd atual |
| profit_loss | REAL | % de lucro/perda |
| close_reason | TEXT | Motivo do fechamento |
| close_time | TIMESTAMP | Momento do fechamento |
| created_at | TIMESTAMP | Data de criação do registro |
| updated_at | TIMESTAMP | Data da última atualização |

### Tabela: `daily_stats`
Estatísticas diárias agregadas

| Campo | Tipo | Descrição |
|-------|------|-----------|
| id | INTEGER | ID auto-incremento (PK) |
| date | DATE | Data (único) |
| total_bets | INTEGER | Total de apostas do dia |
| profit_bets | INTEGER | Apostas com lucro |
| loss_bets | INTEGER | Apostas com perda |
| total_profit | REAL | Lucro total do dia |
| soccer_bets | INTEGER | Apostas de futebol |
| hockey_bets | INTEGER | Apostas de hóquei |
| tennis_bets | INTEGER | Apostas de tênis |

### Tabela: `balance_history`
Histórico de saldo da conta

| Campo | Tipo | Descrição |
|-------|------|-----------|
| id | INTEGER | ID auto-incremento (PK) |
| timestamp | TIMESTAMP | Momento do registro |
| available | REAL | Saldo disponível |
| total | REAL | Saldo total |
| exposure | REAL | Exposição atual |

## 🚀 Como Usar

### 1. Migração de Dados Antigos (Primeira Vez)

Se você já tinha apostas no arquivo JSON antigo (`logs/active_bets.json`), rode o script de migração:

```bash
python migrate_to_database.py
```

Isso irá:
- ✅ Importar todas as apostas do JSON para o banco
- ✅ Criar backup do arquivo JSON
- ✅ Atualizar estatísticas

### 2. Rodar o Bot

O bot agora usa automaticamente o banco de dados:

```bash
python betfair_bot.py
```

Tudo é salvo automaticamente no banco `data/bets.db`

### 3. Acessar o Dashboard

O dashboard agora busca dados direto do banco:

```bash
python dashboard_api.py
```

Acesse: http://localhost:8502

## 📊 Novos Endpoints da API

### GET `/api/data`
Retorna estatísticas e apostas de hoje

```json
{
  "success": true,
  "stats": {
    "total_bets": 45,
    "active_bets": 3,
    "profit_bets": 28,
    "loss_bets": 14,
    "total_profit": 234.50
  },
  "balance": {
    "available": 1234.56,
    "total": 1500.00,
    "exposure": 265.44
  },
  "bets_active": [...],
  "bets_history": [...]
}
```

### GET `/api/stats/history?days=30`
Retorna estatísticas dos últimos N dias

```json
{
  "success": true,
  "stats": [
    {
      "date": "2025-12-17",
      "total_bets": 12,
      "profit_bets": 8,
      "loss_bets": 4,
      "total_profit": 45.30
    },
    ...
  ]
}
```

### GET `/api/bets/history?start_date=2025-12-01&end_date=2025-12-17`
Retorna histórico de apostas por período

```json
{
  "success": true,
  "bets": [...],
  "count": 245
}
```

### GET `/api/bet/<bet_id>`
Retorna detalhes de uma aposta específica

```json
{
  "success": true,
  "bet": {
    "bet_id": "123456789",
    "event_name": "Brasil vs Argentina",
    "status": "CLOSED_PROFIT",
    "profit_loss": 2.5,
    ...
  }
}
```

### GET `/api/balance/history`
Retorna histórico de saldo da conta

```json
{
  "success": true,
  "balance": {
    "timestamp": "2025-12-17T10:30:00",
    "available": 1234.56,
    "total": 1500.00,
    "exposure": 265.44
  }
}
```

## 📁 Localização dos Arquivos

- **Banco de dados**: `data/bets.db`
- **Módulo do banco**: `database.py`
- **Script de migração**: `migrate_to_database.py`

## 🔧 Manutenção

### Backup do Banco de Dados

```bash
# Criar backup manual
cp data/bets.db data/bets_backup_$(date +%Y%m%d).db
```

### Consultar o Banco Diretamente

```bash
# Abrir o banco com SQLite CLI
sqlite3 data/bets.db

# Exemplos de queries
SELECT * FROM bets WHERE status = 'ACTIVE';
SELECT * FROM daily_stats ORDER BY date DESC LIMIT 7;
SELECT COUNT(*) FROM bets WHERE sport = 'SOCCER';
```

### Limpar Dados Antigos (Opcional)

```python
# Exemplo: Deletar apostas com mais de 90 dias
import sqlite3
from datetime import datetime, timedelta

conn = sqlite3.connect('data/bets.db')
cursor = conn.cursor()

cutoff_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
cursor.execute("DELETE FROM bets WHERE DATE(entry_time) < ?", (cutoff_date,))

conn.commit()
conn.close()
```

## 🆘 Troubleshooting

### "database is locked"
O SQLite permite apenas um writer por vez. Se você vir esse erro:
1. Certifique-se de que não há múltiplas instâncias do bot rodando
2. Feche qualquer conexão aberta ao banco
3. Reinicie o bot

### Corromper banco de dados
Se o banco ficar corrompido (muito raro):
```bash
# Exportar para SQL
sqlite3 data/bets.db .dump > backup.sql

# Recriar banco
rm data/bets.db
sqlite3 data/bets.db < backup.sql
```

### Resetar banco completamente
```bash
# CUIDADO: Isso apaga TODOS os dados!
rm data/bets.db
python betfair_bot.py  # Recria o banco vazio
```

## 📈 Próximas Melhorias

- [ ] Gráficos de performance no dashboard
- [ ] Exportar relatórios para CSV/Excel
- [ ] Alertas por email/Telegram quando atingir metas
- [ ] Machine Learning para otimizar estratégias
- [ ] Análise de padrões de vitória/derrota

## 🤝 Contribuindo

Se encontrar bugs ou tiver sugestões, abra uma issue!

---

**Desenvolvido com ❤️ para traders Betfair**
