#!/bin/bash
# Script de entrada para o container Docker

set -e

# Comandos que não precisam de certificados/config
SKIP_CHECK_COMMANDS=("generate_certificate.sh" "./generate_certificate.sh" "bash" "sh" "/bin/bash" "/bin/sh")

# Verificar se o comando atual deve pular as verificações
SKIP_CHECK=false
for cmd in "${SKIP_CHECK_COMMANDS[@]}"; do
    if [[ "$1" == *"$cmd"* ]] || [[ "$*" == *"$cmd"* ]]; then
        SKIP_CHECK=true
        break
    fi
done

# Se não for um comando que precisa pular, fazer verificações
if [ "$SKIP_CHECK" = false ]; then
    echo "=== Betfair API Container ==="
    echo ""
    
    # Verificar se o certificado existe
    if [ ! -f "/app/certs/client-2048.crt" ] || [ ! -f "/app/certs/client-2048.key" ]; then
        echo "⚠️  Certificados não encontrados!"
        echo ""
        echo "Para gerar os certificados, execute:"
        echo "  ./run.sh generate-cert"
        echo "  ou"
        echo "  docker-compose run --rm betfair-api ./generate_certificate.sh"
        echo ""
        exit 1
    fi
    
    # Verificar se o config.ini existe
    if [ ! -f "/app/config.ini" ]; then
        echo "⚠️  Arquivo config.ini não encontrado!"
        echo ""
        echo "Crie o arquivo config.ini baseado em config.ini.example"
        echo "e monte-o no container ou crie dentro do container."
        echo ""
        exit 1
    fi
    
    echo "✓ Certificados encontrados"
    echo "✓ Configuração encontrada"
    echo ""
fi

# Executar comando passado como argumento ou comando padrão
exec "$@"

