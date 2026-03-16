#!/usr/bin/env python3
"""
Dashboard Streamlit Moderno para o Bot de Trading Betfair
"""

import streamlit as st
import pandas as pd
import json
import time
import os
from datetime import datetime, timedelta
from pathlib import Path
import re

# Configurar cache para forçar atualização
if 'force_refresh' not in st.session_state:
    st.session_state.force_refresh = False

# Configurar página
st.set_page_config(
    page_title="Betfair Trading Bot",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS customizado moderno
st.markdown("""
<style>
    /* Cores principais */
    :root {
        --primary: #1f77b4;
        --success: #2ecc71;
        --danger: #e74c3c;
        --warning: #f39c12;
        --info: #3498db;
        --dark: #2c3e50;
        --light: #ecf0f1;
    }
    
    /* Remover espaçamento padrão */
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    
    /* Cards modernos */
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem;
        border-radius: 15px;
        color: white;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        margin-bottom: 1rem;
    }
    
    .bet-card {
        background: white;
        border-radius: 12px;
        padding: 1.5rem;
        margin-bottom: 1rem;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        border-left: 4px solid var(--primary);
        transition: transform 0.2s;
    }
    
    .bet-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    }
    
    .bet-active {
        border-left-color: var(--success);
    }
    
    .bet-profit {
        border-left-color: var(--success);
        background: linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%);
    }
    
    .bet-loss {
        border-left-color: var(--danger);
        background: linear-gradient(135deg, #f8d7da 0%, #f5c6cb 100%);
    }
    
    /* Status badges */
    .status-badge {
        display: inline-block;
        padding: 0.25rem 0.75rem;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
    }
    
    .status-active {
        background: #d4edda;
        color: #155724;
    }
    
    .status-complete {
        background: #cce5ff;
        color: #004085;
    }
    
    /* Título principal */
    .main-title {
        font-size: 2.5rem;
        font-weight: 700;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
    }
    
    /* Sidebar */
    .css-1d391kg {
        background: linear-gradient(180deg, #2c3e50 0%, #34495e 100%);
    }
    
    /* Botões modernos */
    .stButton>button {
        border-radius: 8px;
        border: none;
        padding: 0.5rem 1.5rem;
        font-weight: 600;
        transition: all 0.3s;
    }
    
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
    }
</style>
""", unsafe_allow_html=True)

# Funções auxiliares
def read_log_file():
    """Lê o arquivo de log do bot"""
    possible_paths = [
        Path("logs/bot.log"),
        Path("/app/logs/bot.log"),
        Path("./logs/bot.log"),
    ]
    
    for log_file in possible_paths:
        if log_file.exists():
            try:
                with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                return lines[-200:]  # Últimas 200 linhas
            except Exception as e:
                continue
    
    return []

def read_active_bets_file():
    """Lê o arquivo de apostas ativas"""
    possible_paths = [
        Path("logs/active_bets.json"),
        Path("/app/logs/active_bets.json"),
        Path("./logs/active_bets.json"),
    ]
    
    for bets_file in possible_paths:
        if bets_file.exists():
            try:
                with open(bets_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return data
            except Exception as e:
                continue
    
    return {}

def read_betfair_orders_file():
    """Lê o arquivo de ordens da Betfair"""
    possible_paths = [
        Path("logs/betfair_orders.json"),
        Path("/app/logs/betfair_orders.json"),
        Path("./logs/betfair_orders.json"),
    ]
    
    for orders_file in possible_paths:
        if orders_file.exists():
            try:
                with open(orders_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return data
            except Exception as e:
                continue
    
    return {}

def get_balance_from_orders(orders_data):
    """Calcula saldo e lucro estimado a partir das ordens"""
    if not orders_data or 'currentOrders' not in orders_data:
        return None, None
    
    current_orders = orders_data.get('currentOrders', [])
    if not current_orders:
        return None, None
    
    # Calcular responsabilidade total (exposição)
    total_liability = 0
    total_stake = 0
    
    for order in current_orders:
        side = order.get('side', '')
        price_size = order.get('priceSize', {})
        price = price_size.get('price', 0)
        size = price_size.get('size', 0)
        
        if side == 'LAY' and price > 0 and size > 0:
            liability = size * (price - 1)
            total_liability += liability
            total_stake += size
    
    return total_stake, total_liability

def get_market_info(market_id):
    """Busca informações do mercado (jogo, horário, etc)"""
    try:
        from betfair_api import BetfairAPI
        api = BetfairAPI()
        if not api.login():
            return None
        
        # Buscar informações do mercado
        filter_dict = {
            'marketIds': [market_id]
        }
        
        markets = api.list_market_catalogue(
            filter_dict=filter_dict,
            market_projection=['MARKET_DESCRIPTION', 'RUNNER_DESCRIPTION', 'EVENT', 'MARKET_START_TIME'],
            max_results=1
        )
        
        if markets and len(markets) > 0:
            market = markets[0]
            event = market.get('event', {})
            
            return {
                'event_name': event.get('name', 'N/A'),
                'market_name': market.get('marketName', 'N/A'),
                'event_type': event.get('type', {}).get('name', 'N/A'),
                'start_time': market.get('marketStartTime', 'N/A'),
                'competition': event.get('competition', {}).get('name', 'N/A'),
                'venue': event.get('venue', 'N/A'),
            }
    except Exception as e:
        # Log do erro para debug
        import logging
        logging.error(f"Erro ao buscar info do mercado {market_id}: {e}")
        pass
    
    return None

def get_balance_from_api():
    """Tenta buscar saldo diretamente da API Betfair"""
    try:
        from betfair_api import BetfairAPI
        api = BetfairAPI()
        if api.login():
            funds = api.get_account_funds()
            if funds:
                return {
                    'available': float(funds.get('availableToBetBalance', 0)),
                    'total': float(funds.get('totalBalance', 0)),
                    'exposure': abs(float(funds.get('exposure', 0))),
                    'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
    except Exception as e:
        pass
    return None

def parse_logs(logs):
    """Extrai informações dos logs"""
    stats = {
        'total_bets': 0,
        'profit_bets': 0,
        'loss_bets': 0,
        'total_profit': 0.0,
        'soccer_bets': 0,
        'hockey_bets': 0,
        'tennis_bets': 0,
        'active_bets': 0,
    }
    
    account_balance = {
        'available': None,
        'total': None,
        'exposure': None,
        'last_update': None
    }
    
    for line in logs:
        if 'Total de apostas:' in line:
            match = re.search(r'Total de apostas: (\d+)', line)
            if match:
                stats['total_bets'] = int(match.group(1))
        
        if 'Apostas com lucro:' in line:
            match = re.search(r'Apostas com lucro: (\d+)', line)
            if match:
                stats['profit_bets'] = int(match.group(1))
        
        if 'Apostas com perda:' in line:
            match = re.search(r'Apostas com perda: (\d+)', line)
            if match:
                stats['loss_bets'] = int(match.group(1))
        
        if 'Lucro total:' in line:
            match = re.search(r'Lucro total: R\$ ([\d.]+)', line)
            if match:
                stats['total_profit'] = float(match.group(1))
        
        if 'Apostas ativas:' in line:
            match = re.search(r'Apostas ativas: (\d+)', line)
            if match:
                stats['active_bets'] = int(match.group(1))
        
        if 'Futebol:' in line and 'Hóquei:' in line and 'Tênis:' in line:
            match = re.search(r'Futebol: (\d+) \| Hóquei: (\d+) \| Tênis: (\d+)', line)
            if match:
                stats['soccer_bets'] = int(match.group(1))
                stats['hockey_bets'] = int(match.group(2))
                stats['tennis_bets'] = int(match.group(3))
        
        # Buscar saldo em diferentes formatos
        if 'Saldo disponível:' in line or 'availableToBetBalance' in line or 'Saldo extraído' in line or "'available':" in line:
            # Formato: "Saldo disponível: R$ X.XX"
            match = re.search(r'Saldo disponível: R\$ ([\d.]+)', line)
            if match:
                account_balance['available'] = float(match.group(1))
                account_balance['last_update'] = line.split(' - ')[0] if ' - ' in line else ''
            else:
                # Formato: "Saldo extraído: {'available': X.XX, ...}"
                match = re.search(r"'available':\s*([\d.]+)", line)
                if match:
                    account_balance['available'] = float(match.group(1))
                    account_balance['last_update'] = line.split(' - ')[0] if ' - ' in line else ''
                else:
                    # Formato: "availableToBetBalance': X.XX" ou "availableToBetBalance: X.XX"
                    match = re.search(r'availableToBetBalance[:\s\'"]+([\d.]+)', line)
                    if match:
                        account_balance['available'] = float(match.group(1))
                        account_balance['last_update'] = line.split(' - ')[0] if ' - ' in line else ''
        
        if 'Saldo total:' in line or "'total':" in line or 'totalBalance' in line:
            # Formato: "Saldo total: R$ X.XX"
            match = re.search(r'Saldo total: R\$ ([\d.]+)', line)
            if match:
                account_balance['total'] = float(match.group(1))
            else:
                # Formato: "'total': X.XX" ou "totalBalance: X.XX"
                match = re.search(r"'total':\s*([\d.]+)", line)
                if match:
                    account_balance['total'] = float(match.group(1))
                else:
                    match = re.search(r'totalBalance[:\s]+([\d.]+)', line)
                    if match:
                        account_balance['total'] = float(match.group(1))
        
        if 'Exposição:' in line or "'exposure':" in line or 'exposure' in line.lower():
            # Formato: "Exposição: R$ X.XX"
            match = re.search(r'Exposição: R\$ ([\d.]+)', line)
            if match:
                account_balance['exposure'] = float(match.group(1))
            else:
                # Formato: "'exposure': X.XX" (pode ser negativo)
                match = re.search(r"'exposure':\s*(-?[\d.]+)", line)
                if match:
                    account_balance['exposure'] = abs(float(match.group(1)))  # Valor absoluto
                else:
                    match = re.search(r'exposure[:\s]+(-?[\d.]+)', line)
                    if match:
                        account_balance['exposure'] = abs(float(match.group(1)))
    
    return stats, account_balance

def check_bot_status():
    """Verifica se o bot está rodando"""
    logs = read_log_file()
    if not logs:
        return False
    
    recent_logs = logs[-10:] if len(logs) >= 10 else logs
    
    for log_line in recent_logs:
        if any(keyword in log_line for keyword in [
            'Bot inicializado', 'Bot iniciado', 'Encontradas', 'INFO'
        ]):
            try:
                if ' - ' in log_line:
                    timestamp_str = log_line.split(' - ')[0]
                    log_time = datetime.strptime(timestamp_str[:19], '%Y-%m-%d %H:%M:%S')
                    now = datetime.now()
                    if (now - log_time).total_seconds() < 300:
                        return True
            except:
                return True
    
    return False

# ==================== SIDEBAR ====================
with st.sidebar:
    st.markdown("""
    <div style='text-align: center; padding: 1rem 0;'>
        <h1 style='color: white; margin: 0;'>🤖 Bot Control</h1>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Status do bot
    bot_running = check_bot_status()
    
    if bot_running:
        st.success("🟢 **Bot Online**")
    else:
        st.error("🔴 **Bot Offline**")
    
    st.markdown("---")
    
    # Controles
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("▶️ Iniciar", use_container_width=True):
            try:
                import subprocess
                subprocess.run(["docker", "compose", "-f", "docker-compose.bot.yml", "start", "betfair-bot"], 
                             timeout=10, capture_output=True)
                st.success("✅ Iniciado!")
                time.sleep(1)
                st.rerun()
            except:
                st.warning("Execute: `docker compose start betfair-bot`")
    
    with col2:
        if st.button("⏸️ Parar", use_container_width=True):
            try:
                import subprocess
                subprocess.run(["docker", "compose", "-f", "docker-compose.bot.yml", "stop", "betfair-bot"], 
                             timeout=10, capture_output=True)
                st.success("✅ Parado!")
                time.sleep(1)
                st.rerun()
            except:
                st.warning("Execute: `docker compose stop betfair-bot`")
    
    if st.button("🔄 Reiniciar", use_container_width=True):
        try:
            import subprocess
            subprocess.run(["docker", "compose", "-f", "docker-compose.bot.yml", "restart", "betfair-bot"], 
                         timeout=10, capture_output=True)
            st.success("✅ Reiniciado!")
            time.sleep(1)
            st.rerun()
        except:
            st.warning("Execute: `docker compose restart betfair-bot`")
    
    st.markdown("---")
    
    st.markdown("---")
    
    # Auto-refresh com JavaScript
    auto_refresh = st.checkbox("🔄 Auto-refresh", value=True, key="auto_refresh")
    refresh_interval = st.slider("Intervalo (s)", 5, 60, 10, key="refresh_interval")
    
    # Usar JavaScript para auto-refresh (não bloqueia a UI)
    if auto_refresh:
        st.markdown(f"""
        <script>
            setTimeout(function(){{
                window.location.reload();
            }}, {refresh_interval * 1000});
        </script>
        """, unsafe_allow_html=True)
        st.caption(f"⏱️ Próxima atualização em {refresh_interval} segundos...")
    
    # Botão manual de refresh
    if st.button("🔄 Atualizar Agora", use_container_width=True, key="manual_refresh"):
        st.cache_data.clear()
        if 'last_update_time' in st.session_state:
            st.session_state.last_update_time = datetime.now().strftime('%H:%M:%S')
        st.rerun()

# ==================== HEADER ====================
st.markdown("""
<div style='text-align: center; padding: 2rem 0;'>
    <h1 class='main-title'>🤖 Betfair Trading Bot</h1>
    <p style='color: #666; font-size: 1.1rem;'>Dashboard de Monitoramento em Tempo Real</p>
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ==================== DADOS ====================
# Carregar dados sem cache para garantir atualização
logs = read_log_file()
stats, account_balance = parse_logs(logs)
active_bets_json = read_active_bets_file()
betfair_orders = read_betfair_orders_file()

# Se não encontrou saldo nos logs, tentar buscar da API ou calcular das ordens
if account_balance.get('available') is None:
    # Tentar buscar da API primeiro (apenas se não estiver em modo de leitura)
    try:
        api_balance = get_balance_from_api()
        if api_balance:
            account_balance.update(api_balance)
    except:
        pass
    
    # Se ainda não tem, tentar calcular das ordens
    if account_balance.get('available') is None and betfair_orders:
        total_stake, total_liability = get_balance_from_orders(betfair_orders)
        if total_liability:
            account_balance['exposure'] = total_liability
            if not account_balance.get('last_update'):
                account_balance['last_update'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# Atualizar timestamp
current_time = datetime.now().strftime('%H:%M:%S')
st.session_state.last_update_time = current_time

# ==================== MÉTRICAS PRINCIPAIS ====================
st.markdown("### 📊 Visão Geral")

col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    available = account_balance.get('available')
    if available is not None and available > 0:
        st.metric(
            "💰 Saldo Disponível",
            f"R$ {available:.2f}",
            delta="em caixa"
        )
        if account_balance.get('last_update'):
            st.caption(f"⏰ {account_balance['last_update'][:19]}")
    elif account_balance.get('exposure') is not None:
        # Se não tem saldo disponível mas tem exposição, mostrar exposição
        exposure = account_balance.get('exposure', 0)
        st.metric(
            "💰 Exposição",
            f"R$ {exposure:.2f}",
            delta="em risco"
        )
    else:
        st.metric("💰 Saldo Disponível", "R$ --")
        if st.button("🔄 Buscar Saldo", key="fetch_balance", use_container_width=True):
            api_balance = get_balance_from_api()
            if api_balance:
                account_balance.update(api_balance)
                st.rerun()
            else:
                st.error("Não foi possível buscar saldo")

with col2:
    st.metric(
        "📈 Lucro Total",
        f"R$ {stats['total_profit']:.2f}",
        delta=f"{stats['profit_bets'] - stats['loss_bets']} net"
    )

with col3:
    st.metric(
        "🎯 Total Apostas",
        stats['total_bets'],
        delta=f"{stats['active_bets']} ativas"
    )

with col4:
    win_rate = (stats['profit_bets'] / stats['total_bets'] * 100) if stats['total_bets'] > 0 else 0
    st.metric(
        "✅ Taxa Sucesso",
        f"{win_rate:.1f}%",
        delta=f"{stats['profit_bets']}/{stats['total_bets']}"
    )

with col5:
    avg_profit = (stats['total_profit'] / stats['total_bets']) if stats['total_bets'] > 0 else 0
    st.metric(
        "💵 Lucro Médio",
        f"R$ {avg_profit:.2f}",
        delta="por aposta"
    )

st.markdown("---")

# ==================== TABS ====================
tab1, tab2, tab3, tab4 = st.tabs([
    "🎯 Apostas Ativas", 
    "📊 Estatísticas", 
    "⚽ Por Esporte",
    "📋 Logs"
])

# ==================== TAB 1: APOSTAS ATIVAS ====================
with tab1:
    st.markdown("### 🎯 Suas Apostas Ativas")
    
    # Apostas da Betfair (mais confiável)
    if betfair_orders and 'currentOrders' in betfair_orders:
        current_orders = betfair_orders.get('currentOrders', [])
        
        if current_orders:
            st.markdown(f"**📊 {len(current_orders)} apostas ativas encontradas**")
            st.markdown("---")
            
            for i, order in enumerate(current_orders, 1):
                bet_id = str(order.get('betId', 'N/A'))
                market_id = order.get('marketId', 'N/A')
                selection_id = order.get('selectionId', 'N/A')
                side = order.get('side', 'N/A')
                price_size = order.get('priceSize', {})
                price = price_size.get('price', 'N/A')
                size = price_size.get('size', 'N/A')
                status = order.get('status', 'N/A')
                placed_date = order.get('placedDate', 'N/A')
                
                # Calcular responsabilidade
                liability = 0
                if side == 'LAY' and price != 'N/A' and size != 'N/A':
                    try:
                        liability = float(size) * (float(price) - 1)
                    except:
                        pass
                
                # Buscar informações do mercado
                market_info = get_market_info(market_id)
                
                # Determinar tipo de mercado e esporte
                if selection_id == 47972 or str(selection_id) == '47972':
                    market_type = "Under 2.5 Goals"
                    sport_emoji = "⚽"
                    sport_name = "Futebol"
                    win_condition = "Para GANHAR: O jogo deve ter MENOS de 2.5 gols (0, 1 ou 2 gols)"
                else:
                    market_type = "Match Odds"
                    sport_emoji = "🎾"
                    sport_name = "Tênis"
                    win_condition = "Para GANHAR: O favorito deve vencer o jogo"
                
                # Nome do evento
                event_name = market_info.get('event_name', 'Carregando...') if market_info else 'Carregando...'
                
                # Horário do jogo
                start_time_str = "Carregando..."
                if market_info and market_info.get('start_time') != 'N/A':
                    try:
                        start_time = datetime.fromisoformat(market_info['start_time'].replace('Z', '+00:00'))
                        start_time_str = start_time.strftime('%d/%m/%Y %H:%M')
                        # Calcular horário de término aproximado (futebol: 90min, tênis: variável)
                        if sport_name == "Futebol":
                            end_time = start_time + timedelta(minutes=105)  # 90min + intervalo + acréscimos
                            end_time_str = end_time.strftime('%H:%M')
                            time_range = f"{start_time.strftime('%H:%M')} - {end_time_str}"
                        else:
                            time_range = start_time.strftime('%H:%M') + " (em andamento)"
                    except:
                        time_range = "Horário não disponível"
                else:
                    time_range = "Horário não disponível"
                
                # Card da aposta
                with st.container():
                    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
                    
                    with col1:
                        st.markdown(f"""
                        <div style='padding: 1.5rem; background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%); border-radius: 12px; border-left: 5px solid #2ecc71; margin-bottom: 1rem;'>
                            <h3 style='margin: 0 0 0.5rem 0; color: #2c3e50; font-size: 1.2rem;'>{sport_emoji} {sport_name}</h3>
                            <h4 style='margin: 0 0 0.5rem 0; color: #34495e; font-size: 1rem; font-weight: 600;'>{event_name}</h4>
                            <p style='margin: 0.3rem 0; color: #7f8c8d; font-size: 0.9rem;'>
                                <strong>📊 Mercado:</strong> {market_type} ({side})
                            </p>
                            <p style='margin: 0.3rem 0; color: #27ae60; font-size: 0.85rem; font-weight: 600;'>
                                ✅ {win_condition}
                            </p>
                            <p style='margin: 0.3rem 0; color: #7f8c8d; font-size: 0.85rem;'>
                                ⏰ <strong>Horário:</strong> {time_range}
                            </p>
                            <p style='margin: 0.5rem 0 0 0; color: #95a5a6; font-size: 0.75rem;'>
                                Market ID: {market_id} | Bet ID: {bet_id[:12]}...
                            </p>
                        </div>
                        """, unsafe_allow_html=True)
                    
                    with col2:
                        st.metric("💰 Stake", f"R$ {size}")
                        if liability > 0:
                            st.caption(f"📉 Liab: R$ {liability:.2f}")
                            st.caption("(Valor em risco)")
                    
                    with col3:
                        st.metric("📊 Odd", f"{price}")
                        if status == 'EXECUTION_COMPLETE':
                            st.success("✅ Executada")
                        else:
                            st.caption(f"Status: {status}")
                    
                    with col4:
                        if placed_date and placed_date != 'N/A':
                            try:
                                dt = datetime.fromisoformat(placed_date.replace('Z', '+00:00'))
                                st.write(f"📅 Aposta feita")
                                st.caption(f"{dt.strftime('%d/%m/%Y')}")
                                st.caption(f"{dt.strftime('%H:%M:%S')}")
                            except:
                                st.write("📅 --")
                        else:
                            st.write("📅 --")
                    
                    st.markdown("---")
        else:
            st.info("ℹ️ Nenhuma aposta ativa no momento")
    else:
        st.warning("⚠️ Execute `python3 verificar_apostas.py` para atualizar as apostas")
    
    # Botão para atualizar apostas da Betfair
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("🔄 Atualizar da Betfair", use_container_width=True):
            st.info("Execute: `python3 verificar_apostas.py`")
    with col_btn2:
        if st.button("🔄 Recarregar Dashboard", use_container_width=True):
            st.cache_data.clear()
            st.session_state.last_update_time = datetime.now().strftime('%H:%M:%S')
            st.rerun()

# ==================== TAB 2: ESTATÍSTICAS ====================
with tab2:
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 💰 Informações da Conta")
        
        if account_balance.get('available') is not None:
            balance_data = {
                'Tipo': ['Disponível', 'Total', 'Exposição'],
                'Valor (R$)': [
                    account_balance.get('available', 0),
                    account_balance.get('total', 0),
                    account_balance.get('exposure', 0) if account_balance.get('exposure') else 0
                ]
            }
            df_balance = pd.DataFrame(balance_data)
            st.dataframe(df_balance, use_container_width=True, hide_index=True)
        else:
            st.info("Aguardando dados da conta...")
    
    with col2:
        st.markdown("### 📈 Performance")
        
        performance_data = {
            'Métrica': ['Total', 'Lucro', 'Perda', 'Ativas'],
            'Valor': [
                stats['total_bets'],
                stats['profit_bets'],
                stats['loss_bets'],
                stats['active_bets']
            ]
        }
        df_perf = pd.DataFrame(performance_data)
        st.dataframe(df_perf, use_container_width=True, hide_index=True)
        
        # Gráfico
        if stats['total_bets'] > 0:
            chart_data = pd.DataFrame({
                'Tipo': ['Lucro', 'Perda'],
                'Quantidade': [stats['profit_bets'], stats['loss_bets']]
            })
            st.bar_chart(chart_data.set_index('Tipo'))

# ==================== TAB 3: POR ESPORTE ====================
with tab3:
    st.markdown("### ⚽ Apostas por Esporte")
    
    # Recontar apostas ativas por esporte
    soccer_count = 0
    hockey_count = 0
    tennis_count = 0
    
    if betfair_orders and 'currentOrders' in betfair_orders:
        for order in betfair_orders.get('currentOrders', []):
            selection_id = order.get('selectionId', '')
            if selection_id == 47972 or str(selection_id) == '47972':
                soccer_count += 1
            # Adicionar lógica para outros esportes se necessário
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        total_soccer = max(stats['soccer_bets'], soccer_count)
        st.metric("⚽ Futebol", total_soccer)
        if total_soccer > 0:
            st.caption(f"{soccer_count} ativas")
    
    with col2:
        st.metric("🏒 Hóquei", stats['hockey_bets'])
        if stats['hockey_bets'] > 0:
            st.caption("ativas")
    
    with col3:
        st.metric("🎾 Tênis", stats['tennis_bets'])
        if stats['tennis_bets'] > 0:
            st.caption("ativas")
    
    st.markdown("---")
    
    # Gráfico
    total_sport_bets = total_soccer + stats['hockey_bets'] + stats['tennis_bets']
    if total_sport_bets > 0:
        sport_data = pd.DataFrame({
            'Esporte': ['Futebol', 'Hóquei', 'Tênis'],
            'Apostas': [total_soccer, stats['hockey_bets'], stats['tennis_bets']]
        })
        st.bar_chart(sport_data.set_index('Esporte'))
    else:
        st.info("ℹ️ Nenhuma aposta por esporte registrada ainda")

# ==================== TAB 4: LOGS ====================
with tab4:
    st.markdown("### 📋 Logs do Bot")
    
    if logs:
        log_text = "\n".join(logs[-100:])
        st.text_area("", log_text, height=500, key="logs_display")
    else:
        st.warning("Nenhum log encontrado")

# ==================== FOOTER ====================
st.markdown("---")
st.markdown("""
<div style='text-align: center; color: #7f8c8d; padding: 1rem;'>
    <p>🤖 Betfair Trading Bot Dashboard | Atualizado em tempo real</p>
</div>
""", unsafe_allow_html=True)
