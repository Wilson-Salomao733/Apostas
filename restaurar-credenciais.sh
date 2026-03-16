#!/bin/bash
# ============================================================
# Restaura credenciais a partir dos GitHub Secrets
# Uso: gh secret list (para verificar) e depois ./restaurar-credenciais.sh
#
# Pré-requisito: gh auth login
# ============================================================

set -e

REPO="Wilson-Salomao733/Apostas"

echo "=========================================="
echo "🔐 RESTAURANDO CREDENCIAIS DO GITHUB"
echo "=========================================="

mkdir -p certs

echo "📄 Restaurando config.ini..."
gh secret view CONFIG_INI --repo "$REPO" --json value -q .value > config.ini

echo "📄 Restaurando bot_config.ini..."
gh secret view BOT_CONFIG_INI --repo "$REPO" --json value -q .value > bot_config.ini

echo "🔑 Restaurando certificados..."
gh secret view CERT_CRT --repo "$REPO" --json value -q .value > certs/client-2048.crt
gh secret view CERT_KEY --repo "$REPO" --json value -q .value > certs/client-2048.key
gh secret view CERT_PEM --repo "$REPO" --json value -q .value > certs/client-2048.pem
gh secret view CERT_CSR --repo "$REPO" --json value -q .value > certs/client-2048.csr
gh secret view CERT_P12_B64 --repo "$REPO" --json value -q .value | base64 -d > certs/client-2048.p12

echo ""
echo "✅ Credenciais restauradas com sucesso!"
echo ""
echo "Arquivos restaurados:"
ls -lh config.ini bot_config.ini certs/client-2048.*
echo ""
echo "Agora rode: ./atualizar-docker.sh"
