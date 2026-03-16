#!/bin/bash
# Script helper para facilitar o uso do Docker

set -e

# Cores para output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Betfair API - Docker Helper ===${NC}"
echo ""

# Função para mostrar ajuda
show_help() {
    echo "Uso: ./run.sh [comando]"
    echo ""
    echo "Comandos disponíveis:"
    echo "  build          - Construir a imagem Docker"
    echo "  up             - Iniciar o container"
    echo "  down           - Parar o container"
    echo "  logs           - Ver logs do container"
    echo "  shell          - Abrir shell no container"
    echo "  generate-cert  - Gerar certificado dentro do container"
    echo "  login          - Testar login na API Betfair"
    echo "  api            - Executar exemplo da API"
    echo "  help           - Mostrar esta ajuda"
    echo ""
}

# Verificar se docker-compose está disponível
if ! command -v docker-compose &> /dev/null; then
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}Erro: Docker não está instalado!${NC}"
        exit 1
    else
        # Usar docker compose (versão mais recente)
        DOCKER_COMPOSE="docker compose"
    fi
else
    DOCKER_COMPOSE="docker-compose"
fi

# Processar comando
case "${1:-help}" in
    build)
        echo -e "${YELLOW}Construindo imagem Docker...${NC}"
        $DOCKER_COMPOSE build
        ;;
    
    up)
        echo -e "${YELLOW}Iniciando container...${NC}"
        $DOCKER_COMPOSE up -d
        echo -e "${GREEN}Container iniciado!${NC}"
        echo "Use './run.sh logs' para ver os logs"
        ;;
    
    down)
        echo -e "${YELLOW}Parando container...${NC}"
        $DOCKER_COMPOSE down
        ;;
    
    logs)
        $DOCKER_COMPOSE logs -f betfair-api
        ;;
    
    shell)
        echo -e "${YELLOW}Abrindo shell no container...${NC}"
        $DOCKER_COMPOSE run --rm betfair-api bash
        ;;
    
    generate-cert)
        echo -e "${YELLOW}Gerando certificado no container...${NC}"
        $DOCKER_COMPOSE run --rm betfair-api ./generate_certificate.sh
        echo -e "${GREEN}Certificado gerado em: ./certs/${NC}"
        ;;
    
    login)
        echo -e "${YELLOW}Testando login na API Betfair...${NC}"
        $DOCKER_COMPOSE run --rm betfair-api python betfair_login.py
        ;;
    
    api)
        echo -e "${YELLOW}Executando exemplo da API...${NC}"
        $DOCKER_COMPOSE run --rm betfair-api python betfair_api.py
        ;;
    
    help|*)
        show_help
        ;;
esac

