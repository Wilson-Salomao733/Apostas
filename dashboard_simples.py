#!/usr/bin/env python3
"""
Dashboard SIMPLES e DIRETO para o Bot Betfair
Interface fácil de entender
"""

import streamlit as st
import json
import os
from datetime import datetime
from pathlib import Path

# Configurar página
st.set_page_config(
    page_title="Bot Betfair - Visão Simples",
    page_icon="🤖",
    layout="wide"
)

# Título grande e claro
st.title("🤖 BOT BETFAIR - STATUS")
st.markdown("---")

# Função para ler apostas ativas
def ler_apostas_ativas():
    """Lê o arquivo de apostas ativas"""
    arquivo = Path("logs/active_bets.json")
    if not arquivo.exists():
        return []
    
    try:
        with open(arquivo, 'r') as f:
            dados = json.load(f)
        return dados
    except:
        return []

# Função para ler logs e extrair informações
def ler_estatisticas():
    """Lê os logs e extrai estatísticas"""
    arquivo = Path("logs/bot.log")
    if not arquivo.exists():
        return {
            'total_apostas': 0,
            'apostas_lucro': 0,
            'apostas_perda': 0,
            'lucro_total': 0.0,
            'saldo': None
        }
    
    try:
        with open(arquivo, 'r', encoding='utf-8', errors='ignore') as f:
            linhas = f.readlines()
        
        stats = {
            'total_apostas': 0,
            'apostas_lucro': 0,
            'apostas_perda': 0,
            'lucro_total': 0.0,
            'saldo': None
        }
        
        for linha in linhas[-500:]:  # Últimas 500 linhas
            if 'Total de apostas:' in linha:
                import re
                match = re.search(r'Total de apostas: (\d+)', linha)
                if match:
                    stats['total_apostas'] = int(match.group(1))
            
            if 'Apostas com lucro:' in linha:
                import re
                match = re.search(r'Apostas com lucro: (\d+)', linha)
                if match:
                    stats['apostas_lucro'] = int(match.group(1))
            
            if 'Apostas com perda:' in linha:
                import re
                match = re.search(r'Apostas com perda: (\d+)', linha)
                if match:
                    stats['apostas_perda'] = int(match.group(1))
            
            if 'Lucro total:' in linha:
                import re
                match = re.search(r'Lucro total: R\$ ([\d.]+)', linha)
                if match:
                    stats['lucro_total'] = float(match.group(1))
            
            if 'Saldo disponível:' in linha:
                import re
                match = re.search(r'Saldo disponível: R\$ ([\d.]+)', linha)
                if match:
                    stats['saldo'] = float(match.group(1))
        
        return stats
    except Exception as e:
        return {
            'total_apostas': 0,
            'apostas_lucro': 0,
            'apostas_perda': 0,
            'lucro_total': 0.0,
            'saldo': None
        }

# ============================================
# SEÇÃO 1: INFORMAÇÕES PRINCIPAIS
# ============================================

st.header("💰 INFORMAÇÕES PRINCIPAIS")

# Ler estatísticas
stats = ler_estatisticas()
apostas_ativas = ler_apostas_ativas()

# Contar apostas ativas
apostas_ativas_count = sum(1 for a in apostas_ativas.values() if a.get('status') == 'ACTIVE')

# Criar colunas para métricas
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("💵 SALDO DISPONÍVEL", 
              f"R$ {stats['saldo']:.2f}" if stats['saldo'] else "Carregando...",
              delta=None)

with col2:
    st.metric("📊 TOTAL DE APOSTAS", 
              stats['total_apostas'],
              delta=None)

with col3:
    st.metric("✅ APOSTAS ATIVAS AGORA", 
              apostas_ativas_count,
              delta=None)

with col4:
    cor_lucro = "🟢" if stats['lucro_total'] >= 0 else "🔴"
    st.metric("💰 LUCRO TOTAL", 
              f"{cor_lucro} R$ {stats['lucro_total']:.2f}",
              delta=None)

st.markdown("---")

# ============================================
# SEÇÃO 2: APOSTAS ATIVAS
# ============================================

st.header("🎯 APOSTAS ATIVAS AGORA")

if apostas_ativas_count == 0:
    st.info("📭 Nenhuma aposta ativa no momento")
else:
    # Mostrar cada aposta ativa
    for bet_id, aposta in apostas_ativas.items():
        if aposta.get('status') == 'ACTIVE':
            with st.expander(f"🎲 Aposta {bet_id[:8]}... - {aposta.get('sport', 'N/A')}", expanded=True):
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.write(f"**Esporte:** {aposta.get('sport', 'N/A')}")
                    st.write(f"**Tipo:** {aposta.get('side', 'N/A')}")
                    st.write(f"**Estratégia:** {aposta.get('strategy', 'N/A')}")
                
                with col2:
                    st.write(f"**Preço Entrada:** {aposta.get('entry_price', 0):.2f}")
                    st.write(f"**Preço Atual:** {aposta.get('current_price', 'N/A')}")
                    st.write(f"**Stake:** R$ {aposta.get('stake', 0):.2f}")
                
                with col3:
                    lucro_perda = aposta.get('profit_loss', 0)
                    if lucro_perda:
                        cor = "🟢" if lucro_perda > 0 else "🔴"
                        st.write(f"**P&L:** {cor} {lucro_perda:.2f}%")
                    else:
                        st.write(f"**P&L:** Calculando...")
                    
                    # Data de entrada
                    entry_time = aposta.get('entry_time', '')
                    if entry_time:
                        st.write(f"**Entrada:** {entry_time}")

st.markdown("---")

# ============================================
# SEÇÃO 3: RESULTADOS
# ============================================

st.header("📈 RESULTADOS")

col1, col2 = st.columns(2)

with col1:
    st.subheader("✅ Apostas com Lucro")
    st.metric("", stats['apostas_lucro'], delta=None)

with col2:
    st.subheader("❌ Apostas com Perda")
    st.metric("", stats['apostas_perda'], delta=None)

# Taxa de sucesso
if stats['total_apostas'] > 0:
    taxa_sucesso = (stats['apostas_lucro'] / stats['total_apostas']) * 100
    st.metric("🎯 Taxa de Sucesso", f"{taxa_sucesso:.1f}%", delta=None)

st.markdown("---")

# ============================================
# SEÇÃO 4: STATUS DO BOT
# ============================================

st.header("⚙️ STATUS DO BOT")

# Verificar se o bot está rodando
arquivo_log = Path("logs/bot.log")
if arquivo_log.exists():
    # Ler última linha do log
    try:
        with open(arquivo_log, 'r', encoding='utf-8', errors='ignore') as f:
            linhas = f.readlines()
            ultima_linha = linhas[-1] if linhas else ""
        
        # Verificar se há atividade recente (últimos 2 minutos)
        if 'INFO' in ultima_linha or 'DEBUG' in ultima_linha:
            st.success("✅ Bot está RODANDO")
        else:
            st.warning("⚠️ Bot pode estar parado")
    except:
        st.error("❌ Erro ao verificar status")
else:
    st.error("❌ Arquivo de log não encontrado")

# Botão para atualizar
if st.button("🔄 ATUALIZAR AGORA"):
    st.rerun()

# Auto-refresh
auto_refresh = st.checkbox("🔄 Atualizar automaticamente a cada 30 segundos", value=True)

if auto_refresh:
    import time
    time.sleep(30)
    st.rerun()

st.markdown("---")

# ============================================
# RODAPÉ
# ============================================

st.markdown("""
<div style='text-align: center; color: #666; padding: 20px;'>
    <p>🤖 Bot Betfair - Dashboard Simples</p>
    <p>Última atualização: {}</p>
</div>
""".format(datetime.now().strftime("%d/%m/%Y %H:%M:%S")), unsafe_allow_html=True)
