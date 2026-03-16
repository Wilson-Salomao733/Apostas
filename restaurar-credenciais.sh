#!/bin/bash
# ============================================================
# Restaura credenciais a partir do arquivo criptografado
# Uso: ./restaurar-credenciais.sh
#
# Pré-requisito: gpg instalado (sudo apt install gnupg -y)
# ============================================================

set -e

BACKUP_FILE="credenciais.tar.gz.gpg"

echo "=========================================="
echo "🔐 RESTAURANDO CREDENCIAIS"
echo "=========================================="

if [ ! -f "$BACKUP_FILE" ]; then
    echo "❌ Arquivo $BACKUP_FILE não encontrado!"
    echo "   Certifique-se de estar na pasta do projeto."
    exit 1
fi

echo "🔑 Digite a senha para descriptografar..."
gpg --decrypt "$BACKUP_FILE" | tar -xz

echo ""
echo "✅ Credenciais restauradas com sucesso!"
echo ""
echo "Arquivos restaurados:"
ls -lh config.ini bot_config.ini certs/client-2048.* 2>/dev/null
echo ""
echo "Agora rode: ./atualizar-docker.sh"
