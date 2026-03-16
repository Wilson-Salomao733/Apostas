#!/bin/bash
# Script simples para rodar o bot Betfair

echo "============================================================"
echo "INICIANDO BOT BETFAIR"
echo "============================================================"
echo ""

# Verificar se o diretório de logs existe
if [ ! -d "logs" ]; then
    echo "Criando diretório de logs..."
    mkdir -p logs
fi

# Verificar se os arquivos de configuração existem
if [ ! -f "config.ini" ]; then
    echo "❌ ERRO: Arquivo config.ini não encontrado!"
    exit 1
fi

if [ ! -f "bot_config.ini" ]; then
    echo "❌ ERRO: Arquivo bot_config.ini não encontrado!"
    exit 1
fi

echo "✓ Arquivos de configuração encontrados"
echo "✓ Diretório de logs pronto"
echo ""
echo "Iniciando bot..."
echo "Pressione Ctrl+C para parar"
echo ""
echo "============================================================"
echo ""

# Executar o bot
python3 betfair_bot.py
