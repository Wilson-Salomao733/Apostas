#!/bin/bash

# Script para gerenciar o dashboard API

case "$1" in
  start)
    echo "Iniciando dashboard API..."
    docker compose -f docker-compose.dashboard-api.yml up -d
    echo "✅ Dashboard API iniciado! Acesse: http://localhost:8502"
    ;;
  stop)
    echo "Parando dashboard API..."
    docker compose -f docker-compose.dashboard-api.yml down
    echo "✅ Dashboard API parado."
    ;;
  restart)
    echo "Reiniciando dashboard API..."
    docker compose -f docker-compose.dashboard-api.yml restart
    echo "✅ Dashboard API reiniciado."
    ;;
  logs)
    echo "Mostrando logs do dashboard API..."
    docker compose -f docker-compose.dashboard-api.yml logs -f dashboard-api
    ;;
  status)
    echo "Status do dashboard API:"
    docker compose -f docker-compose.dashboard-api.yml ps
    ;;
  build)
    echo "Construindo imagem do dashboard API..."
    docker compose -f docker-compose.dashboard-api.yml build
    echo "✅ Imagem construída!"
    ;;
  *)
    echo "Uso: $0 {start|stop|restart|logs|status|build}"
    echo ""
    echo "Comandos:"
    echo "  start   - Inicia o dashboard API"
    echo "  stop    - Para o dashboard API"
    echo "  restart - Reinicia o dashboard API"
    echo "  logs    - Mostra logs em tempo real"
    echo "  status  - Mostra status do container"
    echo "  build   - Reconstrói a imagem"
    exit 1
    ;;
esac

exit 0
