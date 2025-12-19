# 🐳 Docker com Banco de Dados - Guia Completo

## 🚀 Início Rápido

### 1. Setup Automático (Recomendado)

```bash
./docker-setup.sh
```

Este script irá:
- ✅ Verificar dependências (Docker, Docker Compose)
- ✅ Criar diretórios necessários
- ✅ Construir as imagens
- ✅ Iniciar os containers
- ✅ Migrar dados antigos automaticamente

### 2. Setup Manual

```bash
# Criar diretórios
mkdir -p logs data certs

# Construir imagens
docker compose -f docker-compose-completo.yml build

# Iniciar containers
docker compose -f docker-compose-completo.yml up -d
```

---

## 📦 O que foi configurado?

### ✅ Bot (betfair-bot)
- Dockerfile atualizado com `database.py`
- Entrypoint inteligente que:
  - Detecta JSON antigo
  - Faz migração automática
  - Inicia o bot
- Volume persistente para `/app/data` (banco de dados)

### ✅ Dashboard (dashboard-api)
- Dockerfile atualizado com `database.py`
- Acesso ao mesmo banco de dados do bot
- Porta 8502 exposta

### ✅ Volumes Compartilhados
Ambos os containers compartilham:
- `./data` → Banco de dados SQLite
- `./logs` → Logs do sistema
- `./certs` → Certificados (read-only)
- `./config.ini` → Configurações (read-only)

---

## 📊 Estrutura dos Arquivos

```
├── Dockerfile.bot                    # Imagem do bot
├── Dockerfile.dashboard-api          # Imagem do dashboard
├── docker-compose-completo.yml       # Compose com bot + dashboard (PRINCIPAL)
├── docker-entrypoint-bot.sh          # Entrypoint com migração automática
├── docker-setup.sh                   # Script de setup automatizado
├── database.py                       # Módulo do banco de dados
├── migrate_to_database.py            # Script de migração
├── view_database.py                  # Visualizador de dados
└── data/
    └── bets.db                       # Banco de dados (criado automaticamente)
```

---

## 🎯 Comandos Úteis

### Gerenciamento Básico

```bash
# Iniciar tudo
docker compose -f docker-compose-completo.yml up -d

# Parar tudo
docker compose -f docker-compose-completo.yml down

# Reiniciar
docker compose -f docker-compose-completo.yml restart

# Ver status
docker compose -f docker-compose-completo.yml ps
```

### Logs

```bash
# Ver logs do bot
docker compose -f docker-compose-completo.yml logs -f betfair-bot

# Ver logs do dashboard
docker compose -f docker-compose-completo.yml logs -f dashboard-api

# Ver logs de ambos
docker compose -f docker-compose-completo.yml logs -f
```

### Banco de Dados

```bash
# Visualizar dados do banco (menu interativo)
docker compose -f docker-compose-completo.yml exec betfair-bot python view_database.py

# Executar migração manualmente
docker compose -f docker-compose-completo.yml exec betfair-bot python migrate_to_database.py

# Acessar SQLite diretamente
docker compose -f docker-compose-completo.yml exec betfair-bot sqlite3 /app/data/bets.db
```

### Backup

```bash
# Backup do banco de dados
cp data/bets.db data/bets_backup_$(date +%Y%m%d_%H%M%S).db

# Restaurar backup
cp data/bets_backup_YYYYMMDD_HHMMSS.db data/bets.db
docker compose -f docker-compose-completo.yml restart
```

### Debugging

```bash
# Entrar no container do bot
docker compose -f docker-compose-completo.yml exec betfair-bot bash

# Entrar no container do dashboard
docker compose -f docker-compose-completo.yml exec dashboard-api bash

# Executar comando específico no bot
docker compose -f docker-compose-completo.yml exec betfair-bot python view_database.py
```

---

## 🔄 Migração Automática

Quando você inicia o bot pela primeira vez com dados antigos:

1. **O entrypoint detecta** `logs/active_bets.json`
2. **Executa automaticamente** `migrate_to_database.py`
3. **Cria backup** do arquivo JSON
4. **Importa tudo** para o banco SQLite
5. **Inicia o bot** normalmente

### Logs da Migração

```
==========================================
🚀 Iniciando Bot Betfair Trading
==========================================

📦 Arquivo JSON de apostas antigas encontrado!
🔄 Executando migração para o banco de dados...

🔄 Iniciando migração de logs/active_bets.json...
📄 Encontradas 15 apostas no arquivo JSON
  ✓ Migrada: 123456789
  ✓ Migrada: 987654321
  ...

==========================================
📊 RESULTADO DA MIGRAÇÃO:
==========================================
  ✓ Migradas com sucesso: 15
  ⚠ Ignoradas (já existem): 0
  ❌ Erros: 0
==========================================

✅ Migração concluída!

==========================================
🤖 Iniciando bot de trading...
==========================================
```

---

## 🌐 Acessando o Dashboard

Após iniciar os containers:

```bash
# O dashboard estará disponível em:
http://localhost:8502
```

O dashboard agora:
- ✅ Busca dados do banco SQLite
- ✅ Mostra histórico completo
- ✅ Estatísticas em tempo real
- ✅ Novos endpoints da API

---

## 📈 Monitoramento

### Ver Estatísticas

```bash
# Opção 1: Menu interativo
docker compose -f docker-compose-completo.yml exec betfair-bot python view_database.py

# Opção 2: Dashboard web
# Acesse http://localhost:8502

# Opção 3: Logs
docker compose -f docker-compose-completo.yml logs betfair-bot | grep "ESTATÍSTICAS"
```

### Ver Apostas Ativas

```bash
docker compose -f docker-compose-completo.yml exec betfair-bot sqlite3 /app/data/bets.db "SELECT bet_id, event_name, sport, side, entry_price, stake FROM bets WHERE status='ACTIVE';"
```

### Ver Histórico de Hoje

```bash
docker compose -f docker-compose-completo.yml exec betfair-bot sqlite3 /app/data/bets.db "SELECT * FROM bets WHERE DATE(entry_time)=DATE('now');"
```

---

## 🔧 Troubleshooting

### Container não inicia

```bash
# Ver logs de erro
docker compose -f docker-compose-completo.yml logs betfair-bot

# Verificar configurações
docker compose -f docker-compose-completo.yml config

# Rebuild completo
docker compose -f docker-compose-completo.yml down
docker compose -f docker-compose-completo.yml build --no-cache
docker compose -f docker-compose-completo.yml up -d
```

### Banco de dados corrompido

```bash
# Fazer dump do banco
docker compose -f docker-compose-completo.yml exec betfair-bot sqlite3 /app/data/bets.db .dump > backup.sql

# Recriar banco
rm data/bets.db
docker compose -f docker-compose-completo.yml exec betfair-bot sqlite3 /app/data/bets.db < backup.sql
```

### Resetar tudo (CUIDADO!)

```bash
# Para os containers
docker compose -f docker-compose-completo.yml down

# Remove banco e logs (BACKUP ANTES!)
rm -rf data/*.db logs/*.log

# Reinicia do zero
docker compose -f docker-compose-completo.yml up -d
```

---

## 🎯 Melhores Práticas

### 1. Backup Regular

Configure um cronjob para backup automático:

```bash
# Adicione ao crontab (crontab -e)
0 3 * * * cp /caminho/para/data/bets.db /caminho/para/backups/bets_$(date +\%Y\%m\%d).db
```

### 2. Monitoramento

```bash
# Ver uso de disco do banco
docker compose -f docker-compose-completo.yml exec betfair-bot du -h /app/data/bets.db

# Ver número de apostas
docker compose -f docker-compose-completo.yml exec betfair-bot sqlite3 /app/data/bets.db "SELECT COUNT(*) FROM bets;"
```

### 3. Limpeza Periódica

```bash
# Remover logs antigos (mais de 30 dias)
find logs/ -name "*.log" -mtime +30 -delete

# Compactar backups antigos
gzip backups/*.db
```

---

## 📚 Recursos Adicionais

- **DATABASE_README.md** - Documentação completa do banco
- **GUIA_BANCO_DADOS.txt** - Guia rápido de referência
- **CHANGELOG_DATABASE.md** - Log de mudanças

---

## 🆘 Suporte

Se encontrar problemas:

1. Verifique os logs: `docker compose logs`
2. Verifique o status: `docker compose ps`
3. Consulte a documentação acima
4. Verifique se os volumes estão montados corretamente

---

**Sistema pronto para produção! 🚀**
