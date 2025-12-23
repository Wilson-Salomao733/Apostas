#!/usr/bin/env python3
"""
API Backend para o Dashboard HTML
Fornece endpoints para buscar dados sem recarregar a página
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import json
import os
import re
from pathlib import Path
from datetime import datetime, timedelta
from betfair_api import BetfairAPI
from database import BetDatabase
from configparser import ConfigParser

app = Flask(__name__)
CORS(app)  # Permitir requisições do frontend

# Inicializar banco de dados
db = BetDatabase()

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
                return lines[-200:]
            except:
                continue
    
    return []

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
            except:
                continue
    
    return {}

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
            match = re.search(r'Saldo disponível: R\$ ([\d.]+)', line)
            if match:
                account_balance['available'] = float(match.group(1))
            else:
                match = re.search(r"'available':\s*([\d.]+)", line)
                if match:
                    account_balance['available'] = float(match.group(1))
                else:
                    match = re.search(r'availableToBetBalance[:\s\'"]+([\d.]+)', line)
                    if match:
                        account_balance['available'] = float(match.group(1))
        
        if 'Saldo total:' in line or "'total':" in line or 'totalBalance' in line:
            match = re.search(r'Saldo total: R\$ ([\d.]+)', line)
            if match:
                account_balance['total'] = float(match.group(1))
            else:
                match = re.search(r"'total':\s*([\d.]+)", line)
                if match:
                    account_balance['total'] = float(match.group(1))
                else:
                    match = re.search(r'totalBalance[:\s]+([\d.]+)', line)
                    if match:
                        account_balance['total'] = float(match.group(1))
        
        if 'Exposição:' in line or "'exposure':" in line or 'exposure' in line.lower():
            match = re.search(r'Exposição: R\$ ([\d.]+)', line)
            if match:
                account_balance['exposure'] = abs(float(match.group(1)))
            else:
                match = re.search(r"'exposure':\s*(-?[\d.]+)", line)
                if match:
                    account_balance['exposure'] = abs(float(match.group(1)))
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
        if any(keyword in log_line for keyword in ['Bot inicializado', 'Bot iniciado', 'Encontradas', 'INFO']):
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

@app.route('/api/data', methods=['GET'])
def get_data():
    """Endpoint para buscar todos os dados do banco de dados"""
    try:
        # Buscar estatísticas do banco de dados
        stats = db.get_statistics()
        
        # Buscar saldo mais recente do banco
        balance_data = db.get_latest_balance()
        account_balance = {
            'available': balance_data['available'] if balance_data else None,
            'total': balance_data['total'] if balance_data else None,
            'exposure': balance_data['exposure'] if balance_data else None,
        }
        
        # Tentar buscar saldo atualizado da API se possível
        api = None
        try:
            api = BetfairAPI()
            if api.login():
                funds = api.get_account_funds()
                if funds:
                    account_balance['available'] = float(funds.get('availableToBetBalance', 0))
                    account_balance['total'] = float(funds.get('totalBalance', 0))
                    account_balance['exposure'] = abs(float(funds.get('exposure', 0)))
                    # Salvar no banco para histórico
                    db.save_balance(
                        account_balance['available'],
                        account_balance['total'],
                        account_balance['exposure']
                    )
        except Exception:
            pass
        
        # Buscar apostas do banco de dados
        # Buscar apostas ativas (últimas 24 horas - já filtrado no método)
        active_bets_db = db.get_active_bets()
        
        # Buscar apostas fechadas dos últimos 2 dias apenas
        end_date = datetime.now()
        start_date = end_date - timedelta(days=2)
        closed_bets_db = db.get_bets_by_date_range(
            start_date.strftime('%Y-%m-%d'),
            end_date.strftime('%Y-%m-%d')
        )
        # Filtrar apenas as fechadas
        closed_bets_db = [b for b in closed_bets_db if b['status'] != 'ACTIVE']
        
        # Combinar todas as apostas
        all_bets_db = active_bets_db + closed_bets_db
        
        # Converter apostas do banco para o formato da API
        bets = []
        active_bets = []
        history_bets = []
        
        for bet_db in all_bets_db:
            bet_data = {
                'bet_id': bet_db['bet_id'],
                'market_id': bet_db['market_id'],
                'event_id': bet_db['event_id'],
                'event_name': bet_db['event_name'],
                'selection_id': bet_db['selection_id'],
                'side': bet_db['side'],
                'price': bet_db['entry_price'],
                'size': bet_db['stake'],
                'status': bet_db['status'],
                'placed_date': bet_db['entry_time'],
                'placedDate': bet_db['entry_time'],
                'sport': bet_db['sport'],
                'strategy': bet_db['strategy'],
                'current_price': bet_db.get('current_price'),
                'profit_loss': bet_db.get('profit_loss'),
                'close_reason': bet_db.get('close_reason'),
                'close_time': bet_db.get('close_time'),
                'take_profit_pct': bet_db.get('take_profit_pct'),
                'stop_loss_pct': bet_db.get('stop_loss_pct'),
                'game_score': bet_db.get('game_score'),
                'market_status': bet_db.get('market_status'),
                'runner_status': bet_db.get('runner_status'),
                'gross_profit': bet_db.get('gross_profit'),
                'net_profit': bet_db.get('net_profit'),
            }
            
            bets.append(bet_data)
            
            # Classificar entre ativa e histórico
            # ATIVAS: status = ACTIVE E das últimas 24 horas (já filtrado no get_active_bets)
            # HISTÓRICO: todas as outras (CLOSED_PROFIT, CLOSED_LOSS, CLOSED_TIMEOUT, etc)
            if bet_db['status'] == 'ACTIVE':
                # Verificar se é das últimas 24 horas (segurança extra)
                agora = datetime.now()
                vinte_quatro_horas_atras = agora - timedelta(hours=24)
                
                # Parse da data de entrada
                try:
                    entry_time_str = bet_db['entry_time']
                    if 'T' in entry_time_str:
                        entry_datetime = datetime.fromisoformat(entry_time_str.replace('Z', '+00:00'))
                        # Remover timezone para comparação
                        if entry_datetime.tzinfo:
                            entry_datetime = entry_datetime.replace(tzinfo=None)
                    else:
                        entry_datetime = datetime.strptime(entry_time_str, '%Y-%m-%d %H:%M:%S')
                except:
                    # Se falhar o parse, usar data atual como fallback
                    entry_datetime = agora
                
                # Só adicionar se for das últimas 24 horas
                if entry_datetime >= vinte_quatro_horas_atras:
                    active_bets.append(bet_data)
                # Se não tem nome válido, não adiciona em active_bets (fica apenas em bets para histórico)
            else:
                history_bets.append(bet_data)
        
        return jsonify({
            'success': True,
            'stats': stats,
            'balance': account_balance,
            'bets': bets,
            'bets_active': active_bets,
            'bets_history': history_bets,
            'bot_status': check_bot_status()
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/market/<market_id>', methods=['GET'])
def get_market_info(market_id):
    """Endpoint para buscar informações de um mercado específico"""
    try:
        api = BetfairAPI()
        if not api.login():
            return jsonify({'success': False, 'error': 'Falha no login'}), 500
        
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
            
            return jsonify({
                'success': True,
                'event_name': event.get('name', 'N/A'),
                'market_name': market.get('marketName', 'N/A'),
                'event_type': event.get('type', {}).get('name', 'N/A'),
                'start_time': market.get('marketStartTime', 'N/A'),
                'competition': event.get('competition', {}).get('name', 'N/A'),
                'venue': event.get('venue', 'N/A'),
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Mercado não encontrado'
            }), 404
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/stats/history', methods=['GET'])
def get_stats_history():
    """Endpoint para buscar histórico de estatísticas diárias"""
    try:
        days = int(request.args.get('days', 30))
        stats = db.get_daily_stats(days)
        
        return jsonify({
            'success': True,
            'stats': stats
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/bets/history', methods=['GET'])
def get_bets_history():
    """Endpoint para buscar histórico completo de apostas"""
    try:
        # Parâmetros opcionais
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        status = request.args.get('status')
        
        if start_date and end_date:
            bets = db.get_bets_by_date_range(start_date, end_date)
        elif status:
            bets = db.get_bets_by_status(status.upper())
        else:
            # Últimos 30 dias por padrão
            from datetime import timedelta
            end = datetime.now()
            start = end - timedelta(days=30)
            bets = db.get_bets_by_date_range(
                start.strftime('%Y-%m-%d'),
                end.strftime('%Y-%m-%d')
            )
        
        return jsonify({
            'success': True,
            'bets': bets,
            'count': len(bets)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/bet/<bet_id>', methods=['GET'])
def get_bet_details(bet_id):
    """Endpoint para buscar detalhes de uma aposta específica"""
    try:
        bet = db.get_bet(bet_id)
        
        if bet:
            return jsonify({
                'success': True,
                'bet': bet
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Aposta não encontrada'
            }), 404
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/bet/<bet_id>/check-settled', methods=['POST'])
def check_bet_settled(bet_id):
    """Endpoint para verificar e atualizar uma aposta com dados da API de atividade"""
    try:
        from check_settled_bets import check_and_update_settled_bets
        from betfair_api import BetfairAPI
        
        api = BetfairAPI()
        if not api.login():
            return jsonify({
                'success': False,
                'error': 'Falha no login da API'
            }), 500
        
        bet = db.get_bet(bet_id)
        if not bet:
            return jsonify({
                'success': False,
                'error': 'Aposta não encontrada'
            }), 404
        
        # Buscar dados do mercado
        market_result = api.get_market_result(bet['market_id'])
        
        update_data = {}
        
        if market_result:
            # Atualizar status do mercado
            market_status = market_result.get('market_status')
            if market_status:
                db.update_bet_game_info(bet_id, market_status=market_status)
                update_data['market_status'] = market_status
            
            # Buscar informações do runner
            runners = market_result.get('runners', [])
            for runner in runners:
                if str(runner.get('selection_id')) == str(bet['selection_id']):
                    runner_status = runner.get('status', '')
                    result = runner.get('result', '')
                    
                    if runner_status:
                        db.update_bet_game_info(bet_id, runner_status=runner_status)
                        update_data['runner_status'] = runner_status
                    
                    if result:
                        update_data['result'] = result
                    
                    break
        
        # Tentar buscar dados da API de atividade
        settled_data = api.get_settled_bets(bet_ids=[bet_id])
        
        if settled_data and 'bets' in settled_data:
            for settled_bet in settled_data['bets']:
                settled_bet_id = settled_bet.get('betId', '')
                # A API pode retornar com ou sem prefixo "1:"
                if settled_bet_id == bet_id or settled_bet_id == f"1:{bet_id}" or settled_bet_id.endswith(bet_id):
                    db.update_bet_settled_data(bet_id, settled_bet)
                    update_data['gross_profit'] = settled_bet.get('grossProfit')
                    update_data['net_profit'] = settled_bet.get('netProfit')
                    break
        
        # Buscar aposta atualizada
        updated_bet = db.get_bet(bet_id)
        
        return jsonify({
            'success': True,
            'bet': updated_bet,
            'updates': update_data
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/bets/check-all-settled', methods=['POST'])
def check_all_settled_bets():
    """Endpoint para verificar e atualizar todas as apostas recentes"""
    try:
        from check_settled_bets import check_and_update_settled_bets
        
        check_and_update_settled_bets()
        
        return jsonify({
            'success': True,
            'message': 'Verificação concluída'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/balance/history', methods=['GET'])
def get_balance_history():
    """Endpoint para buscar histórico de saldo"""
    try:
        # Por enquanto retorna apenas o último saldo
        # Futuramente pode retornar histórico completo
        latest = db.get_latest_balance()
        
        return jsonify({
            'success': True,
            'balance': latest if latest else {}
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/bot/status', methods=['GET'])
def check_docker_availability():
    """Verifica se Docker está disponível para controlar o bot"""
    try:
        import subprocess
        import os
        
        # Verificar se docker está disponível
        try:
            result = subprocess.run(
                ['docker', '--version'],
                capture_output=True,
                timeout=2
            )
            docker_available = result.returncode == 0
        except:
            docker_available = False
        
        # Verificar se docker-compose está disponível
        docker_compose_available = False
        possible_paths = [
            'docker compose',
            'docker-compose',
        ]
        
        for cmd in possible_paths:
            try:
                result = subprocess.run(
                    cmd.split() + ['--version'],
                    capture_output=True,
                    timeout=2
                )
                if result.returncode == 0:
                    docker_compose_available = True
                    break
            except:
                continue
        
        return jsonify({
            'success': True,
            'docker_available': docker_available,
            'docker_compose_available': docker_compose_available,
            'can_control': docker_available and docker_compose_available
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'docker_available': False,
            'docker_compose_available': False,
            'can_control': False,
            'error': str(e)
        })

@app.route('/api/bot/<action>', methods=['POST'])
def control_bot(action):
    """Endpoint para controlar o bot"""
    try:
        import subprocess
        import os
        import json as json_lib
        
        # Verificar se estamos em Docker e se temos acesso ao socket Docker
        docker_socket = '/var/run/docker.sock'
        has_docker_access = os.path.exists(docker_socket)
        
        if not has_docker_access:
            return jsonify({
                'success': False,
                'message': 'Socket Docker não encontrado. Verifique se /var/run/docker.sock está montado.'
            }), 503
        
        # Nome do container do bot
        container_name = 'betfair-trading-bot'
        
        # Tentar usar Docker diretamente (mais confiável)
        docker_cmd = None
        if os.path.exists('/usr/bin/docker') or os.path.exists('/usr/local/bin/docker'):
            # Verificar se docker está disponível
            try:
                result = subprocess.run(
                    ['docker', '--version'],
                    capture_output=True,
                    timeout=2
                )
                if result.returncode == 0:
                    docker_cmd = 'docker'
            except:
                pass
        
        # Se docker direto não funcionar, tentar docker-compose
        if not docker_cmd:
            possible_paths = [
                'docker compose',  # Docker Compose V2
                'docker-compose',  # Docker Compose V1
            ]
            
            for cmd in possible_paths:
                try:
                    result = subprocess.run(
                        cmd.split() + ['--version'],
                        capture_output=True,
                        timeout=2
                    )
                    if result.returncode == 0:
                        docker_cmd = cmd
                        break
                except:
                    continue
        
        if not docker_cmd:
            return jsonify({
                'success': False, 
                'message': 'Docker não encontrado. Execute os comandos manualmente no terminal.'
            }), 503
        
        # Usar Docker diretamente para controlar o container
        if docker_cmd == 'docker':
            # Comandos Docker diretos
            if action == 'start':
                cmd = ['docker', 'start', container_name]
            elif action == 'stop':
                cmd = ['docker', 'stop', container_name]
            elif action == 'restart':
                cmd = ['docker', 'restart', container_name]
            else:
                return jsonify({'success': False, 'message': 'Ação inválida'}), 400
        else:
            # Usar docker-compose
            compose_file = 'docker-compose-completo.yml'
            if not os.path.exists(compose_file):
                compose_file = 'docker-compose.bot.yml'
            
            service_name = 'betfair-bot'
            if action == 'start':
                cmd = docker_cmd.split() + ['-f', compose_file, 'start', service_name]
            elif action == 'stop':
                cmd = docker_cmd.split() + ['-f', compose_file, 'stop', service_name]
            elif action == 'restart':
                cmd = docker_cmd.split() + ['-f', compose_file, 'restart', service_name]
            else:
                return jsonify({'success': False, 'message': 'Ação inválida'}), 400
        
        # Executar comando
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=15,
                text=True
            )
            
            if result.returncode == 0:
                return jsonify({
                    'success': True, 
                    'message': f'Bot {action} executado com sucesso'
                })
            else:
                error_msg = result.stderr or result.stdout or 'Erro desconhecido'
                # Tentar verificar se o container existe
                check_cmd = ['docker', 'ps', '-a', '--filter', f'name={container_name}', '--format', '{{.Names}}']
                check_result = subprocess.run(check_cmd, capture_output=True, text=True, timeout=5)
                
                if check_result.returncode == 0 and container_name in check_result.stdout:
                    return jsonify({
                        'success': False,
                        'message': f'Erro ao executar: {error_msg}\n\nContainer encontrado. Tente manualmente:\ndocker {action} {container_name}'
                    }), 500
                else:
                    return jsonify({
                        'success': False,
                        'message': f'Container não encontrado ou erro: {error_msg}\n\nExecute manualmente:\ndocker {action} {container_name}'
                    }), 500
                    
        except subprocess.TimeoutExpired:
            return jsonify({
                'success': False,
                'message': 'Timeout ao executar comando Docker'
            }), 504
        except FileNotFoundError:
            return jsonify({
                'success': False,
                'message': 'Docker não encontrado. Execute os comandos manualmente no terminal.'
            }), 503
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'Erro: {str(e)}\n\nExecute manualmente:\ndocker {action} {container_name}'
            }), 500
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Erro geral: {str(e)}'
        }), 500

@app.route('/api/config', methods=['GET'])
def get_config():
    """Lê as configurações do bot_config.ini"""
    try:
        config_paths = [
            Path('bot_config.ini'),
            Path('/app/bot_config.ini'),
            Path('./bot_config.ini'),
        ]
        
        config_file = None
        for path in config_paths:
            if path.exists():
                config_file = path
                break
        
        if not config_file:
            return jsonify({
                'success': False,
                'message': 'Arquivo bot_config.ini não encontrado'
            }), 404
        
        config = ConfigParser()
        config.read(config_file)
        
        return jsonify({
            'success': True,
            'config': {
                'stake': float(config.get('bot', 'stake', fallback='15.0')),
                'max_bets_per_sport': int(config.get('bot', 'max_bets_per_sport', fallback='20')),
                'check_interval': int(config.get('bot', 'check_interval', fallback='30')),
                'min_odd': float(config.get('soccer', 'min_odd', fallback='1.30')),
                'under_goals': float(config.get('soccer', 'under_goals', fallback='4.5')),
                'check_time_window': config.getboolean('soccer', 'check_time_window', fallback=True),
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Erro ao ler configurações: {str(e)}'
        }), 500

@app.route('/api/config', methods=['POST'])
def save_config():
    """Salva as configurações no bot_config.ini"""
    try:
        data = request.get_json()
        
        config_paths = [
            Path('bot_config.ini'),
            Path('/app/bot_config.ini'),
            Path('./bot_config.ini'),
        ]
        
        config_file = None
        for path in config_paths:
            if path.exists():
                config_file = path
                break
        
        if not config_file:
            return jsonify({
                'success': False,
                'message': 'Arquivo bot_config.ini não encontrado'
            }), 404
        
        # Ler configuração atual
        config = ConfigParser()
        config.read(config_file)
        
        # Atualizar valores se fornecidos
        if 'stake' in data:
            config.set('bot', 'stake', str(data['stake']))
        if 'max_bets_per_sport' in data:
            config.set('bot', 'max_bets_per_sport', str(data['max_bets_per_sport']))
        if 'check_interval' in data:
            config.set('bot', 'check_interval', str(data['check_interval']))
        if 'min_odd' in data:
            config.set('soccer', 'min_odd', str(data['min_odd']))
        if 'under_goals' in data:
            config.set('soccer', 'under_goals', str(data['under_goals']))
        if 'check_time_window' in data:
            config.set('soccer', 'check_time_window', str(data['check_time_window']).lower())
        
        # Salvar arquivo
        with open(config_file, 'w', encoding='utf-8') as f:
            config.write(f)
        
        return jsonify({
            'success': True,
            'message': 'Configurações salvas com sucesso! Reinicie o bot para aplicar as mudanças.'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Erro ao salvar configurações: {str(e)}'
        }), 500

@app.route('/api/bet/<bet_id>/cashout', methods=['POST'])
def cashout_bet(bet_id):
    """Faz cashout de uma aposta específica (fecha a posição fazendo hedge)"""
    try:
        # Buscar informações da aposta
        orders = BetfairAPI().list_current_orders()
        if not orders:
            return jsonify({
                'success': False,
                'message': 'Não foi possível buscar apostas ativas'
            }), 500
        
        current_orders = orders.get('currentOrders', [])
        bet_order = None
        
        for order in current_orders:
            if str(order.get('betId')) == str(bet_id):
                bet_order = order
                break
        
        if not bet_order:
            return jsonify({
                'success': False,
                'message': 'Aposta não encontrada ou já foi fechada'
            }), 404
        
        market_id = bet_order.get('marketId')
        selection_id = bet_order.get('selectionId')
        side = bet_order.get('side')  # 'BACK' ou 'LAY'
        size_matched = bet_order.get('sizeMatched', 0)
        price_size = bet_order.get('priceSize', {})
        original_price = price_size.get('price', 0)
        original_stake = size_matched
        
        if size_matched == 0:
            return jsonify({
                'success': False,
                'message': 'Aposta não foi executada ainda'
            }), 400
        
        # Buscar odds atuais do mercado
        api = BetfairAPI()
        if not api.login():
            return jsonify({
                'success': False,
                'message': 'Erro ao fazer login na Betfair'
            }), 500
        
        market_book = api.list_market_book(
            market_ids=[market_id],
            price_projection={'priceData': ['EX_BEST_OFFERS']}
        )
        
        if not market_book:
            return jsonify({
                'success': False,
                'message': 'Não foi possível obter dados do mercado'
            }), 500
        
        market = market_book[0]
        runners = market.get('runners', [])
        
        # Encontrar o runner correto
        target_runner = None
        for runner in runners:
            runner_id = runner.get('id') or runner.get('selectionId')
            if str(runner_id) == str(selection_id):
                target_runner = runner
                break
        
        if not target_runner:
            return jsonify({
                'success': False,
                'message': 'Runner não encontrado no mercado'
            }), 404
        
        # Determinar lado oposto e calcular stake do hedge
        if side == 'BACK':
            # Para fechar BACK, fazemos LAY
            hedge_side = 'LAY'
            available_to_lay = target_runner.get('ex', {}).get('availableToLay', [])
            if not available_to_lay:
                return jsonify({
                    'success': False,
                    'message': 'Não há liquidez disponível para fazer LAY'
                }), 400
            hedge_price = available_to_lay[0].get('price', 0)
            # Cálculo: hedge_stake = (back_stake * back_price) / lay_price
            hedge_stake = (original_stake * original_price) / hedge_price
        else:  # side == 'LAY'
            # Para fechar LAY, fazemos BACK
            hedge_side = 'BACK'
            available_to_back = target_runner.get('ex', {}).get('availableToBack', [])
            if not available_to_back:
                return jsonify({
                    'success': False,
                    'message': 'Não há liquidez disponível para fazer BACK'
                }), 400
            hedge_price = available_to_back[0].get('price', 0)
            # Cálculo: hedge_stake = lay_stake / back_price
            hedge_stake = original_stake / hedge_price
        
        if hedge_price <= 1.0 or hedge_stake <= 0:
            return jsonify({
                'success': False,
                'message': 'Preço ou stake inválido para hedge'
            }), 400
        
        # Fazer a aposta de hedge
        instruction = {
            'instructionType': 'PLACE',
            'selectionId': int(selection_id),
            'handicap': 0.0,
            'side': hedge_side,
            'orderType': 'LIMIT',
            'limitOrder': {
                'size': round(hedge_stake, 2),
                'price': round(hedge_price, 2),
                'persistenceType': 'LAPSE'
            }
        }
        
        result = api.place_orders(
            market_id=str(market_id),
            instructions=[instruction],
            customer_ref=f"cashout_{bet_id}_{int(datetime.now().timestamp())}"
        )
        
        if result and 'instructionReports' in result:
            report = result['instructionReports'][0]
            if report.get('status') == 'SUCCESS':
                hedge_bet_id = report.get('betId')
                return jsonify({
                    'success': True,
                    'message': f'Cash Out realizado com sucesso! Bet ID: {hedge_bet_id}',
                    'hedge_bet_id': hedge_bet_id
                })
            else:
                error_code = report.get('errorCode', 'UNKNOWN')
                error_message = report.get('errorMessage', 'Erro desconhecido')
                return jsonify({
                    'success': False,
                    'message': f'Erro ao fazer cashout: {error_code} - {error_message}'
                }), 400
        else:
            return jsonify({
                'success': False,
                'message': 'Resposta inesperada da API'
            }), 500
            
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Erro ao fazer cashout: {str(e)}'
        }), 500

@app.route('/')
def index():
    """Serve o arquivo HTML"""
    html_path = Path('dashboard.html')
    if html_path.exists():
        with open(html_path, 'r', encoding='utf-8') as f:
            return f.read()
    return "Dashboard HTML não encontrado", 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8502, debug=True)
