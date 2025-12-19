#!/bin/bash
# Script para atualizar containers Docker com as últimas mudanças

set -e

echo "=========================================="
echo "🔄 ATUALIZANDO CONTAINERS DOCKER"
echo "=========================================="
echo ""

COMPOSE_FILE="docker-compose-completo.yml"

# Cores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_info() {
    echo "ℹ️  $1"
}

# 1. Parar containers
echo "1️⃣  Parando containers..."
docker compose -f $COMPOSE_FILE down
print_success "Containers parados"
echo ""

# 2. Rebuild das imagens
echo "2️⃣  Reconstruindo imagens com código atualizado..."
docker compose -f $COMPOSE_FILE build --no-cache
print_success "Imagens reconstruídas"
echo ""

# 3. Iniciar containers
echo "3️⃣  Iniciando containers..."
docker compose -f $COMPOSE_FILE up -d
print_success "Containers iniciados"
echo ""

# 4. Verificar status
echo "4️⃣  Status dos containers:"
docker compose -f $COMPOSE_FILE ps
echo ""

# 5. Instruções finais
echo "=========================================="
echo "✅ ATUALIZAÇÃO CONCLUÍDA!"
echo "=========================================="
echo ""
print_info "Dashboard disponível em: http://localhost:8502"
echo ""
print_info "Ver logs:"
echo "  docker compose -f $COMPOSE_FILE logs -f"
echo ""
print_info "Ver apenas logs do dashboard:"
echo "  docker compose -f $COMPOSE_FILE logs -f dashboard-api"
echo ""
print_success "Sistema atualizado e rodando!"
echo ""
