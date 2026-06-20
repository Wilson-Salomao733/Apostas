#!/bin/bash
set -e

echo "=========================================="
echo "🚀 Iniciando Bot Betfair Trading"
echo "=========================================="

# Verificar se existe arquivo JSON antigo para migrar
if [ -f "/app/logs/active_bets.json" ]; then
    echo ""
    echo "📦 Arquivo JSON de apostas antigas encontrado!"
    echo "🔄 Executando migração para o banco de dados..."
    echo ""
    
    python migrate_to_database.py
    
    echo ""
    echo "✅ Migração concluída!"
    echo ""
else
    echo ""
    echo "ℹ️  Nenhum arquivo JSON antigo encontrado."
    echo "📊 O banco de dados será criado automaticamente."
    echo ""
fi

# Verificar se o banco de dados existe
if [ -f "/app/data/bets.db" ]; then
    echo "✅ Banco de dados encontrado: /app/data/bets.db"
    
    # Mostrar tamanho do banco
    DB_SIZE=$(du -h /app/data/bets.db | cut -f1)
    echo "📊 Tamanho do banco: $DB_SIZE"
else
    echo "🆕 Criando novo banco de dados..."
fi

echo ""
echo "=========================================="
echo "🤖 Iniciando bot de trading..."
echo "=========================================="
echo ""

# Executar o bot
exec python manual_bot.py
