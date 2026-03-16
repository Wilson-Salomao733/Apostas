#!/bin/bash

# Script de setup inicial para API Betfair
# Execute: bash setup.sh

echo "=========================================="
echo "  SETUP INICIAL - API BETFAIR"
echo "=========================================="
echo ""

# Verificar se Python está instalado
echo "1. Verificando Python..."
if ! command -v python3 &> /dev/null; then
    echo "   ✗ Python 3 não encontrado. Por favor, instale Python 3.7+"
    exit 1
fi
PYTHON_VERSION=$(python3 --version)
echo "   ✓ $PYTHON_VERSION encontrado"
echo ""

# Verificar se OpenSSL está instalado
echo "2. Verificando OpenSSL..."
if ! command -v openssl &> /dev/null; then
    echo "   ✗ OpenSSL não encontrado. Por favor, instale OpenSSL"
    echo "   No Ubuntu/Debian: sudo apt-get install openssl"
    exit 1
fi
OPENSSL_VERSION=$(openssl version)
echo "   ✓ $OPENSSL_VERSION encontrado"
echo ""

# Criar ambiente virtual (opcional)
read -p "3. Deseja criar um ambiente virtual Python? (s/n): " create_venv
if [[ $create_venv == "s" || $create_venv == "S" ]]; then
    echo "   Criando ambiente virtual..."
    python3 -m venv venv
    echo "   ✓ Ambiente virtual criado em: venv/"
    echo "   Para ativar: source venv/bin/activate"
    echo ""
fi

# Instalar dependências
echo "4. Instalando dependências Python..."
if [[ $create_venv == "s" || $create_venv == "S" ]]; then
    source venv/bin/activate
fi
pip install -r requirements.txt
echo "   ✓ Dependências instaladas"
echo ""

# Gerar certificado
read -p "5. Deseja gerar o certificado agora? (s/n): " generate_cert
if [[ $generate_cert == "s" || $generate_cert == "S" ]]; then
    echo "   Gerando certificado..."
    bash generate_certificate.sh
    echo ""
fi

# Verificar config.ini
echo "6. Verificando configuração..."
if [ ! -f "config.ini" ]; then
    echo "   ⚠ Arquivo config.ini não encontrado"
    echo "   Criando a partir do exemplo..."
    cp config.ini.example config.ini
    echo "   ✓ Arquivo config.ini criado"
    echo ""
    echo "   ⚠ IMPORTANTE: Edite o arquivo config.ini com suas credenciais:"
    echo "      - username: seu usuário Betfair"
    echo "      - password: sua senha Betfair"
    echo "      - app_key: sua Application Key (obtenha em https://developer.betfair.com/)"
    echo ""
else
    echo "   ✓ Arquivo config.ini encontrado"
    echo ""
fi

echo "=========================================="
echo "  SETUP CONCLUÍDO!"
echo "=========================================="
echo ""
echo "PRÓXIMOS PASSOS:"
echo ""
echo "1. Se ainda não fez, gere o certificado:"
echo "   bash generate_certificate.sh"
echo ""
echo "2. Faça upload do certificado no Betfair:"
echo "   https://myaccount.betfair.com/accountdetails/mysecurity?showAPI=1"
echo "   (Use o arquivo: certs/client-2048.crt)"
echo ""
echo "3. Obtenha sua Application Key:"
echo "   https://developer.betfair.com/"
echo ""
echo "4. Configure suas credenciais no arquivo config.ini"
echo ""
echo "5. Teste o login:"
echo "   python3 betfair_login.py"
echo ""
echo "6. Use a API:"
echo "   python3 betfair_api.py"
echo ""
echo "Para mais detalhes, consulte: GUIA_RAPIDO.md"
echo ""

