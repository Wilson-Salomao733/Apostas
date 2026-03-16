#!/bin/bash

# Script interativo para configurar config.ini
# Execute: bash configurar.sh

echo "=========================================="
echo "  CONFIGURAÇÃO DO config.ini"
echo "=========================================="
echo ""

# Verificar se config.ini existe
if [ ! -f "config.ini" ]; then
    echo "Criando config.ini a partir do exemplo..."
    cp config.ini.example config.ini
fi

# Ler valores atuais (se existirem)
CURRENT_USERNAME=$(grep "^username" config.ini | cut -d'=' -f2 | xargs)
CURRENT_PASSWORD=$(grep "^password" config.ini | cut -d'=' -f2 | xargs)
CURRENT_APP_KEY=$(grep "^app_key" config.ini | cut -d'=' -f2 | xargs)
CURRENT_JURISDICTION=$(grep "^jurisdiction" config.ini | cut -d'=' -f2 | xargs)

echo "Preencha as informações abaixo:"
echo "(Pressione Enter para manter o valor atual entre colchetes)"
echo ""

# Solicitar username
if [ -z "$CURRENT_USERNAME" ] || [ "$CURRENT_USERNAME" == "seu_usuario_aqui" ]; then
    read -p "Username da Betfair: " username
else
    read -p "Username da Betfair [$CURRENT_USERNAME]: " username
    if [ -z "$username" ]; then
        username="$CURRENT_USERNAME"
    fi
fi

# Solicitar password
if [ -z "$CURRENT_PASSWORD" ] || [ "$CURRENT_PASSWORD" == "sua_senha_aqui" ]; then
    read -sp "Password da Betfair (não será exibida): " password
    echo ""
else
    read -sp "Password da Betfair (pressione Enter para manter atual): " password
    echo ""
    if [ -z "$password" ]; then
        password="$CURRENT_PASSWORD"
    fi
fi

# Solicitar app_key
if [ -z "$CURRENT_APP_KEY" ] || [ "$CURRENT_APP_KEY" == "sua_app_key_aqui" ]; then
    echo ""
    echo "Para obter a Application Key:"
    echo "1. Acesse: https://developer.betfair.com/"
    echo "2. Faça login e vá em 'My Applications'"
    echo "3. Crie uma aplicação ou use uma existente"
    echo "4. Copie a Application Key"
    echo ""
    read -p "Application Key: " app_key
else
    read -p "Application Key [$CURRENT_APP_KEY]: " app_key
    if [ -z "$app_key" ]; then
        app_key="$CURRENT_APP_KEY"
    fi
fi

# Solicitar jurisdiction
echo ""
echo "Jurisdição:"
echo "  com     = Internacional/Brasil"
echo "  com.au  = Austrália/Nova Zelândia"
echo "  it      = Itália"
echo "  es      = Espanha"
echo "  ro      = Romênia"
if [ -z "$CURRENT_JURISDICTION" ]; then
    read -p "Jurisdição [com]: " jurisdiction
    if [ -z "$jurisdiction" ]; then
        jurisdiction="com"
    fi
else
    read -p "Jurisdição [$CURRENT_JURISDICTION]: " jurisdiction
    if [ -z "$jurisdiction" ]; then
        jurisdiction="$CURRENT_JURISDICTION"
    fi
fi

# Criar backup do config.ini atual
cp config.ini config.ini.backup

# Criar novo config.ini
cat > config.ini << EOF
[betfair]
# Seu nome de usuário da Betfair
username = $username

# Sua senha da Betfair
password = $password

# Application Key (obtenha em: https://developer.betfair.com/)
app_key = $app_key

# Caminho para o arquivo de certificado (.crt)
cert_file = certs/client-2048.crt

# Caminho para o arquivo de chave privada (.key)
key_file = certs/client-2048.key

# Jurisdição (com, com.au, it, es, ro)
# Use 'com' para internacional, 'com.au' para Austrália, etc.
jurisdiction = $jurisdiction

EOF

echo ""
echo "=========================================="
echo "  CONFIGURAÇÃO CONCLUÍDA!"
echo "=========================================="
echo ""
echo "✓ Arquivo config.ini atualizado"
echo "✓ Backup salvo em: config.ini.backup"
echo ""
echo "PRÓXIMOS PASSOS:"
echo ""
echo "1. Certifique-se de que o certificado foi carregado no Betfair:"
echo "   https://myaccount.betfair.com/accountdetails/mysecurity?showAPI=1"
echo ""
echo "2. Teste o login:"
echo "   python3 betfair_login.py"
echo ""

