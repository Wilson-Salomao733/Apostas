#!/bin/bash

# Script para gerenciar o Dashboard

case "$1" in
  start)
    echo "Iniciando dashboard..."
    docker compose -f docker-compose.dashboard.yml up -d
    echo "Dashboard iniciado!"
    echo "Acesse: http://localhost:8501"
    ;;
  stop)
    echo "Parando dashboard..."
    docker compose -f docker-compose.dashboard.yml down
    echo "Dashboard parado."
    ;;
  restart)
    echo "Reiniciando dashboard..."
    docker compose -f docker-compose.dashboard.yml restart
    echo "Dashboard reiniciado."
    ;;
  logs)
    echo "Mostrando logs do dashboard..."
    docker compose -f docker-compose.dashboard.yml logs -f dashboard
    ;;
  build)
    echo "Construindo imagem do dashboard..."
    docker compose -f docker-compose.dashboard.yml build
    echo "Imagem construída!"
    ;;
  *)
    echo "Uso: $0 {start|stop|restart|logs|build}"
    echo ""
    echo "Comandos:"
    echo "  start   - Inicia o dashboard"
    echo "  stop    - Para o dashboard"
    echo "  restart - Reinicia o dashboard"
    echo "  logs    - Mostra logs em tempo real"
    echo "  build   - Reconstrói a imagem"
    exit 1
    ;;
esac

exit 0

