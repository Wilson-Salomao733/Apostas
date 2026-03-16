#!/bin/bash
# Comandos rápidos para gerenciar o sistema Docker

COMPOSE_FILE="docker-compose-completo.yml"

case "$1" in
    start)
        echo "🚀 Iniciando sistema..."
        docker compose -f $COMPOSE_FILE up -d
        echo "✅ Sistema iniciado!"
        echo "🌐 Dashboard: http://localhost:8502"
        ;;
    
    stop)
        echo "🛑 Parando sistema..."
        docker compose -f $COMPOSE_FILE down
        echo "✅ Sistema parado!"
        ;;
    
    restart)
        echo "🔄 Reiniciando sistema..."
        docker compose -f $COMPOSE_FILE restart
        echo "✅ Sistema reiniciado!"
        ;;
    
    logs)
        echo "📊 Logs (Ctrl+C para sair)..."
        docker compose -f $COMPOSE_FILE logs -f
        ;;
    
    logs-bot)
        echo "📊 Logs do Bot (Ctrl+C para sair)..."
        docker compose -f $COMPOSE_FILE logs -f betfair-bot
        ;;
    
    logs-dash)
        echo "📊 Logs do Dashboard (Ctrl+C para sair)..."
        docker compose -f $COMPOSE_FILE logs -f dashboard-api
        ;;
    
    status)
        echo "📊 Status dos containers:"
        docker compose -f $COMPOSE_FILE ps
        ;;
    
    view-db)
        echo "💾 Abrindo visualizador do banco de dados..."
        docker compose -f $COMPOSE_FILE exec betfair-bot python view_database.py
        ;;
    
    migrate)
        echo "🔄 Executando migração..."
        docker compose -f $COMPOSE_FILE exec betfair-bot python migrate_to_database.py
        ;;
    
    backup)
        BACKUP_FILE="data/bets_backup_$(date +%Y%m%d_%H%M%S).db"
        echo "💾 Criando backup..."
        cp data/bets.db "$BACKUP_FILE"
        echo "✅ Backup criado: $BACKUP_FILE"
        ;;
    
    shell-bot)
        echo "🐚 Abrindo shell no container do bot..."
        docker compose -f $COMPOSE_FILE exec betfair-bot bash
        ;;
    
    shell-dash)
        echo "🐚 Abrindo shell no container do dashboard..."
        docker compose -f $COMPOSE_FILE exec dashboard-api bash
        ;;
    
    rebuild)
        echo "🔨 Rebuilding sistema..."
        docker compose -f $COMPOSE_FILE down
        docker compose -f $COMPOSE_FILE build --no-cache
        docker compose -f $COMPOSE_FILE up -d
        echo "✅ Rebuild completo!"
        ;;
    
    clean)
        echo "⚠️  ATENÇÃO: Isso vai remover containers, imagens e volumes!"
        read -p "Tem certeza? (s/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Ss]$ ]]; then
            docker compose -f $COMPOSE_FILE down -v
            docker system prune -f
            echo "✅ Limpeza completa!"
        else
            echo "❌ Operação cancelada"
        fi
        ;;
    
    *)
        echo "🐳 Comandos Rápidos - Bot Betfair Trading"
        echo ""
        echo "Uso: ./docker-quick-commands.sh [comando]"
        echo ""
        echo "Comandos disponíveis:"
        echo "  start       - Iniciar sistema"
        echo "  stop        - Parar sistema"
        echo "  restart     - Reiniciar sistema"
        echo "  logs        - Ver logs de tudo"
        echo "  logs-bot    - Ver logs do bot"
        echo "  logs-dash   - Ver logs do dashboard"
        echo "  status      - Ver status dos containers"
        echo "  view-db     - Visualizar banco de dados"
        echo "  migrate     - Executar migração de dados"
        echo "  backup      - Criar backup do banco"
        echo "  shell-bot   - Abrir shell no container do bot"
        echo "  shell-dash  - Abrir shell no container do dashboard"
        echo "  rebuild     - Rebuild completo do sistema"
        echo "  clean       - Limpar tudo (containers, imagens, volumes)"
        echo ""
        echo "Exemplos:"
        echo "  ./docker-quick-commands.sh start"
        echo "  ./docker-quick-commands.sh logs-bot"
        echo "  ./docker-quick-commands.sh view-db"
        echo ""
        ;;
esac
