#!/bin/bash

# Script para gerenciar o bot de trading Betfair

# Detectar qual comando docker compose está disponível
if command -v docker &> /dev/null; then
    # Tentar docker compose (versão nova) primeiro
    if docker compose version &> /dev/null; then
        DOCKER_COMPOSE="docker compose"
    elif command -v docker-compose &> /dev/null; then
        DOCKER_COMPOSE="docker-compose"
    else
        echo "❌ Erro: docker compose não encontrado!"
        echo "Instale com: sudo apt install docker-compose"
        exit 1
    fi
else
    echo "❌ Erro: Docker não está instalado ou não está rodando!"
    exit 1
fi

case "$1" in
  start)
    echo "============================================================"
    echo "🚀 INICIANDO BOT DE TRADING BETFAIR"
    echo "============================================================"
    echo ""
    
    # Verificar se os arquivos necessários existem
    if [ ! -f "config.ini" ]; then
        echo "❌ ERRO: Arquivo config.ini não encontrado!"
        exit 1
    fi
    
    if [ ! -f "bot_config.ini" ]; then
        echo "❌ ERRO: Arquivo bot_config.ini não encontrado!"
        exit 1
    fi
    
    # Criar diretório de logs se não existir
    mkdir -p logs
    
    echo "✓ Arquivos de configuração encontrados"
    echo "✓ Diretório de logs pronto"
    echo ""
    echo "Construindo imagem (se necessário)..."
    $DOCKER_COMPOSE -f docker-compose.bot.yml build --quiet
    
    echo "Iniciando container..."
    $DOCKER_COMPOSE -f docker-compose.bot.yml up -d
    
    echo ""
    echo "✅ Bot iniciado com sucesso!"
    echo ""
    echo "📊 Comandos úteis:"
    echo "   Ver logs:        ./run_bot.sh logs"
    echo "   Ver status:      ./run_bot.sh status"
    echo "   Parar bot:       ./run_bot.sh stop"
    echo ""
    echo "============================================================"
    ;;
  stop)
    echo "Parando bot..."
    $DOCKER_COMPOSE -f docker-compose.bot.yml down
    echo "✅ Bot parado."
    ;;
  restart)
    echo "Reiniciando bot..."
    $DOCKER_COMPOSE -f docker-compose.bot.yml restart
    echo "✅ Bot reiniciado."
    ;;
  logs)
    echo "Mostrando logs do bot (Ctrl+C para sair)..."
    echo ""
    $DOCKER_COMPOSE -f docker-compose.bot.yml logs -f betfair-bot
    ;;
  status)
    echo "Status do bot:"
    echo ""
    $DOCKER_COMPOSE -f docker-compose.bot.yml ps
    echo ""
    docker ps --filter "name=betfair-trading-bot" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    ;;
  build)
    echo "Construindo imagem do bot..."
    $DOCKER_COMPOSE -f docker-compose.bot.yml build
    echo "✅ Imagem construída!"
    ;;
  *)
    echo "Uso: $0 {start|stop|restart|logs|status|build}"
    echo ""
    echo "Comandos:"
    echo "  start   - Inicia o bot no container Docker"
    echo "  stop    - Para o bot"
    echo "  restart - Reinicia o bot"
    echo "  logs    - Mostra logs em tempo real"
    echo "  status  - Mostra status do container"
    echo "  build   - Reconstrói a imagem"
    exit 1
    ;;
esac

exit 0

