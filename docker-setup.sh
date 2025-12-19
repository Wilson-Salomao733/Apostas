#!/bin/bash
# Script para configurar e iniciar o sistema completo com Docker

set -e

echo "=========================================="
echo "🐳 SETUP DOCKER - BOT BETFAIR TRADING"
echo "=========================================="
echo ""

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Função para prints coloridos
print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_info() {
    echo "ℹ️  $1"
}

# 1. Verificar se Docker está instalado
echo "1️⃣  Verificando Docker..."
if ! command -v docker &> /dev/null; then
    print_error "Docker não encontrado! Instale o Docker primeiro."
    exit 1
fi
print_success "Docker encontrado: $(docker --version)"
echo ""

# 2. Verificar se Docker Compose está disponível
echo "2️⃣  Verificando Docker Compose..."
if ! docker compose version &> /dev/null; then
    print_error "Docker Compose não encontrado!"
    exit 1
fi
print_success "Docker Compose encontrado: $(docker compose version)"
echo ""

# 3. Criar diretórios necessários
echo "3️⃣  Criando diretórios..."
mkdir -p logs data certs
print_success "Diretórios criados"
echo ""

# 4. Verificar arquivos de configuração
echo "4️⃣  Verificando configurações..."
if [ ! -f "config.ini" ]; then
    print_warning "config.ini não encontrado! Copie config.ini.example e configure."
    if [ -f "config.ini.example" ]; then
        cp config.ini.example config.ini
        print_info "Arquivo config.ini.example copiado para config.ini"
        print_warning "CONFIGURE suas credenciais em config.ini antes de continuar!"
    fi
else
    print_success "config.ini encontrado"
fi

if [ ! -f "bot_config.ini" ]; then
    print_warning "bot_config.ini não encontrado!"
else
    print_success "bot_config.ini encontrado"
fi
echo ""

# 5. Verificar certificados
echo "5️⃣  Verificando certificados..."
if [ ! -f "certs/client-2048.key" ] || [ ! -f "certs/client-2048.crt" ]; then
    print_warning "Certificados não encontrados em certs/"
    print_info "Execute: docker compose -f docker-compose.bot.yml run --rm betfair-bot bash"
    print_info "E dentro do container: ./generate_certificate.sh"
else
    print_success "Certificados encontrados"
fi
echo ""

# 6. Parar containers existentes
echo "6️⃣  Parando containers existentes..."
docker compose -f docker-compose-completo.yml down 2>/dev/null || true
print_success "Containers parados"
echo ""

# 7. Construir imagens
echo "7️⃣  Construindo imagens Docker..."
echo ""
docker compose -f docker-compose-completo.yml build --no-cache
echo ""
print_success "Imagens construídas"
echo ""

# 8. Verificar se há dados JSON antigos para migrar
echo "8️⃣  Verificando dados antigos..."
if [ -f "logs/active_bets.json" ]; then
    print_warning "Encontrado arquivo JSON de apostas antigas!"
    print_info "O bot fará migração automática ao iniciar."
    echo ""
    read -p "Deseja fazer backup do JSON agora? (s/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Ss]$ ]]; then
        BACKUP_FILE="logs/active_bets_backup_$(date +%Y%m%d_%H%M%S).json"
        cp logs/active_bets.json "$BACKUP_FILE"
        print_success "Backup criado: $BACKUP_FILE"
    fi
else
    print_info "Nenhum arquivo JSON antigo encontrado"
fi
echo ""

# 9. Iniciar containers
echo "9️⃣  Iniciando containers..."
echo ""
docker compose -f docker-compose-completo.yml up -d
echo ""
print_success "Containers iniciados!"
echo ""

# 10. Mostrar status
echo "🔟 Status dos containers:"
echo ""
docker compose -f docker-compose-completo.yml ps
echo ""

# 11. Aviso sobre Docker Socket
echo ""
echo "=========================================="
echo "⚠️  AVISO DE SEGURANÇA"
echo "=========================================="
echo ""
print_warning "O dashboard monta o socket Docker por padrão."
echo "Isso permite que os botões de controle funcionem."
echo ""
echo "✅ Seguro para:"
echo "   - Uso pessoal/local"
echo "   - Desenvolvimento"
echo "   - Ambientes controlados"
echo ""
echo "⚠️  Cuidado em:"
echo "   - Servidores públicos"
echo "   - Ambientes multi-usuário"
echo "   - Produção sem autenticação"
echo ""
echo "Para remover, edite docker-compose-completo.yml"
echo "e comente a linha do docker.sock"
echo ""

# 12. Instruções finais
echo "=========================================="
echo "✅ SETUP CONCLUÍDO!"
echo "=========================================="
echo ""
print_info "Comandos úteis:"
echo ""
echo "  📊 Ver logs do bot:"
echo "     docker compose -f docker-compose-completo.yml logs -f betfair-bot"
echo ""
echo "  📊 Ver logs do dashboard:"
echo "     docker compose -f docker-compose-completo.yml logs -f dashboard-api"
echo ""
echo "  🌐 Acessar dashboard:"
echo "     http://localhost:8502"
echo ""
echo "  🎮 Botões do dashboard:"
echo "     Agora funcionam! (Iniciar, Parar, Reiniciar)"
echo ""
echo "  🛑 Parar tudo:"
echo "     docker compose -f docker-compose-completo.yml down"
echo ""
echo "  🔄 Reiniciar:"
echo "     docker compose -f docker-compose-completo.yml restart"
echo ""
echo "  💾 Backup do banco:"
echo "     cp data/bets.db data/bets_backup_\$(date +%Y%m%d).db"
echo ""
echo "  🔍 Ver dados do banco:"
echo "     docker compose -f docker-compose-completo.yml exec betfair-bot python view_database.py"
echo ""
print_success "Sistema pronto para usar!"
echo ""
