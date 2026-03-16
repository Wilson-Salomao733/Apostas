#!/bin/bash

# Script para gerar certificado autoassinado para API Betfair
# Execute: bash generate_certificate.sh

echo "=== Gerando Certificado Autoassinado para Betfair API ==="
echo ""

# Criar diretório para certificados se não existir
mkdir -p certs
cd certs

# Gerar chave privada RSA de 2048 bits
echo "1. Gerando chave privada RSA..."
openssl genrsa -out client-2048.key 2048

if [ $? -ne 0 ]; then
    echo "Erro ao gerar chave privada. Certifique-se de que o OpenSSL está instalado."
    exit 1
fi

echo "✓ Chave privada gerada: client-2048.key"
echo ""

# Criar arquivo de configuração OpenSSL
echo "2. Criando arquivo de configuração OpenSSL..."
cat > openssl_betfair.cnf << 'EOF'
[req]
distinguished_name = req_distinguished_name
req_extensions = ssl_client
prompt = no

[req_distinguished_name]
C = GB
ST = London
L = London
O = Betfair API Client
OU = Security Team
CN = Betfair API-NG Certificate
emailAddress = api@betfair.com

[ssl_client]
basicConstraints = CA:FALSE
nsCertType = client
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = clientAuth
EOF

echo "✓ Arquivo de configuração criado: openssl_betfair.cnf"
echo ""

# Criar Certificate Signing Request (CSR) de forma não-interativa
echo "3. Criando Certificate Signing Request (CSR)..."
openssl req -new -config openssl_betfair.cnf -key client-2048.key -out client-2048.csr -batch

if [ $? -ne 0 ]; then
    echo "Erro ao criar CSR."
    exit 1
fi

echo "✓ CSR criado: client-2048.csr"
echo ""

# Auto-assinar o certificado
echo "4. Auto-assinando o certificado..."
openssl x509 -req -days 365 -in client-2048.csr -signkey client-2048.key -out client-2048.crt -extfile openssl_betfair.cnf -extensions ssl_client

if [ $? -ne 0 ]; then
    echo "Erro ao auto-assinar certificado."
    exit 1
fi

echo "✓ Certificado criado: client-2048.crt"
echo ""

# Criar arquivo PEM (certificado + chave)
echo "5. Criando arquivo PEM..."
cat client-2048.crt client-2048.key > client-2048.pem
echo "✓ Arquivo PEM criado: client-2048.pem"
echo ""

# Criar arquivo PKCS#12 (para .NET e outras aplicações)
echo "6. Criando arquivo PKCS#12..."
echo "Você será solicitado a criar uma senha para o arquivo .p12"
openssl pkcs12 -export -in client-2048.crt -inkey client-2048.key -out client-2048.p12

if [ $? -ne 0 ]; then
    echo "Erro ao criar arquivo PKCS#12."
    exit 1
fi

echo "✓ Arquivo PKCS#12 criado: client-2048.p12"
echo ""

cd ..

echo "=== Certificado gerado com sucesso! ==="
echo ""
echo "Arquivos criados em: certs/"
echo "  - client-2048.key  (chave privada - MANTENHA SEGURO!)"
echo "  - client-2048.crt  (certificado - faça upload no Betfair)"
echo "  - client-2048.pem  (certificado + chave)"
echo "  - client-2048.p12  (formato PKCS#12)"
echo ""
echo "PRÓXIMOS PASSOS:"
echo "1. Acesse: https://myaccount.betfair.com/accountdetails/mysecurity?showAPI=1"
echo "2. Vá até 'Automated Betting Program Access' e clique em 'Edit'"
echo "3. Faça upload do arquivo: certs/client-2048.crt"
echo "4. Configure suas credenciais no arquivo config.ini"
echo "5. Execute: python betfair_login.py"
echo ""

