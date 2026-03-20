#!/usr/bin/env python3
"""
Bot de Trading Betfair - Opção A (Time Decay)
Suporta: Futebol, Hóquei e Tênis
"""

import time
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum
from betfair_api import BetfairAPI
from configparser import ConfigParser
from database import BetDatabase
from telegram_notifier import TelegramNotifier
from jogos_ao_vivo import get_inplay_scores

        # Configurar logging
logging.basicConfig(
    level=logging.DEBUG,  # Mudado para DEBUG para ver mais informações
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Reduzir verbosidade de algumas bibliotecas
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)


class SportType(Enum):
    """Tipos de esportes suportados"""
    SOCCER = "Soccer"  # Futebol
    ICE_HOCKEY = "Ice Hockey"  # Hóquei
    TENNIS = "Tennis"  # Tênis


class BetStatus(Enum):
    """Status de uma aposta"""
    PENDING = "pending"  # Aguardando entrada
    ACTIVE = "active"  # Aposta ativa
    CLOSED_PROFIT = "closed_profit"  # Fechada com lucro
    CLOSED_LOSS = "closed_loss"  # Fechada com perda
    CLOSED_TIMEOUT = "closed_timeout"  # Fechada por timeout


@dataclass
class ActiveBet:
    """Representa uma aposta ativa"""
    bet_id: str
    market_id: str
    event_id: str
    sport: SportType
    strategy: str
    side: str  # "LAY" ou "BACK"
    selection_id: str
    entry_price: float
    entry_time: datetime
    stake: float
    liability: float
    take_profit_pct: float
    stop_loss_pct: float
    status: BetStatus = BetStatus.ACTIVE
    current_price: Optional[float] = None
    profit_loss: Optional[float] = None
    close_reason: Optional[str] = None


class BetfairTradingBot:
    """Bot de trading para Betfair com estratégias de Time Decay"""
    
    def __init__(self, config_file='config.ini', bot_config_file='bot_config.ini'):
        """Inicializa o bot"""
        self.config = ConfigParser()
        self.config.read(config_file)
        
        # Salvar caminho do arquivo de configuração para recarregar depois
        self.bot_config_file = bot_config_file
        self.bot_config = ConfigParser()
        self.bot_config.read(bot_config_file)
        
        # Configurações do bot
        self.stake = float(self.bot_config.get('bot', 'stake', fallback='50.0'))
        self.max_bets_per_sport = int(self.bot_config.get('bot', 'max_bets_per_sport', fallback='10'))
        self.check_interval = int(self.bot_config.get('bot', 'check_interval', fallback='30'))  # segundos
        
        # Configurações por esporte
        self.soccer_config = {
            'enabled': self.bot_config.getboolean('soccer', 'enabled', fallback=True),
            'entry_min_minute': int(self.bot_config.get('soccer', 'entry_min_minute', fallback='1')),
            'entry_max_minute': int(self.bot_config.get('soccer', 'entry_max_minute', fallback='45')),
            'entry_goal_line': float(self.bot_config.get('soccer', 'entry_goal_line', fallback='1.5')),
            'entry_odds_min': float(self.bot_config.get('soccer', 'entry_odds_min', fallback='1.80')),
            'entry_odds_max': float(self.bot_config.get('soccer', 'entry_odds_max', fallback='2.20')),
            'take_profit_pct': float(self.bot_config.get('soccer', 'take_profit_pct', fallback='1.5')),
            'stop_loss_pct': float(self.bot_config.get('soccer', 'stop_loss_pct', fallback='10.0')),
            'timeout_minutes': int(self.bot_config.get('soccer', 'timeout_minutes', fallback='10')),
            # Over 0.5 Gols: odd baixa (1.01-1.50) = BACK Over 0.5 (ganha quando sai 1 gol)
            'over_05_odds_min': float(self.bot_config.get('soccer', 'over_05_odds_min', fallback='1.20')),
            'over_05_odds_max': float(self.bot_config.get('soccer', 'over_05_odds_max', fallback='1.50')),
            'min_odd': float(self.bot_config.get('soccer', 'min_odd', fallback='2.15')),
            'max_odd': self._get_optional_float_config('soccer', 'max_odd'),
            'under_25_min_odd': float(self.bot_config.get('soccer', 'under_25_min_odd', fallback='1.35')),
            'under_25_max_odd': self._get_optional_float_config('soccer', 'under_25_max_odd'),
            'cs00_fallback_min_minute': int(self.bot_config.get('soccer', 'cs00_fallback_min_minute', fallback='88')),
            'under_15_emergency_min_minute': int(self.bot_config.get('soccer', 'under_15_emergency_min_minute', fallback='93')),
            'check_time_window': self.bot_config.getboolean('soccer', 'check_time_window', fallback=True),
            'pre_match_enabled': self.bot_config.getboolean('soccer', 'pre_match_enabled', fallback=True),
            'under_hedge_enabled': self.bot_config.getboolean('soccer', 'under_hedge_enabled', fallback=False),
            'under_hedge_stake': float(self.bot_config.get('soccer', 'under_hedge_stake', fallback='15.0')),
            'under_hedge_min_minute': int(self.bot_config.get('soccer', 'under_hedge_min_minute', fallback='73')),
            'require_game_time_to_bet': self.bot_config.getboolean('soccer', 'require_game_time_to_bet', fallback=True),
            'stop_loss_lay_enabled': self.bot_config.getboolean('soccer', 'stop_loss_lay_enabled', fallback=False),
            'stop_loss_lay_threshold': float(self.bot_config.get('soccer', 'stop_loss_lay_threshold', fallback='2.0')),
            'under_high_hedge_enabled': self.bot_config.getboolean('soccer', 'under_high_hedge_enabled', fallback=False),
            'under_high_hedge_stake': float(self.bot_config.get('soccer', 'under_high_hedge_stake', fallback='15.0')),
            'under_high_hedge_min_odd': float(self.bot_config.get('soccer', 'under_high_hedge_min_odd', fallback='1.15')),
            'under_high_hedge_min_odd_first_entry': float(self.bot_config.get('soccer', 'under_high_hedge_min_odd_first_entry', fallback='1.08')),
            'under_high_hedge_trigger_minute': int(self.bot_config.get('soccer', 'under_high_hedge_trigger_minute', fallback='40')),
            'under_high_hedge_end_minute': int(self.bot_config.get('soccer', 'under_high_hedge_end_minute', fallback='88')),
            'under_high_hedge_max_entries': int(self.bot_config.get('soccer', 'under_high_hedge_max_entries', fallback='2')),
            'under_high_hedge_second_entry_minute': int(self.bot_config.get('soccer', 'under_high_hedge_second_entry_minute', fallback='60')),
        }
        
        self.hockey_config = {
            'enabled': self.bot_config.getboolean('hockey', 'enabled', fallback=True),
            'entry_min_minute': int(self.bot_config.get('hockey', 'entry_min_minute', fallback='3')),
            'entry_max_minute': int(self.bot_config.get('hockey', 'entry_max_minute', fallback='5')),
            'take_profit_pct': float(self.bot_config.get('hockey', 'take_profit_pct', fallback='2.0')),
            'stop_loss_pct': float(self.bot_config.get('hockey', 'stop_loss_pct', fallback='15.0')),
            'timeout_minutes': int(self.bot_config.get('hockey', 'timeout_minutes', fallback='5')),
        }
        
        self.tennis_config = {
            'enabled': self.bot_config.getboolean('tennis', 'enabled', fallback=True),
            'entry_min_odd': float(self.bot_config.get('tennis', 'entry_min_odd', fallback='1.80')),
            'entry_max_odd': float(self.bot_config.get('tennis', 'entry_max_odd', fallback='2.20')),
            'max_concurrent_bets': int(self.bot_config.get('tennis', 'max_concurrent_bets', fallback='7')),
            'take_profit_pct': float(self.bot_config.get('tennis', 'take_profit_pct', fallback='3.0')),
            'stop_loss_pct': float(self.bot_config.get('tennis', 'stop_loss_pct', fallback='10.0')),
        }
        
        # Configuração de Trading Pré-Jogo (Green Book)
        self.pre_match_trading_config = {
            'enabled': self.bot_config.getboolean('pre_match_trading', 'enabled', fallback=False),
            'stake': float(self.bot_config.get('pre_match_trading', 'stake', fallback='15.0')),
            'take_profit_pct': float(self.bot_config.get('pre_match_trading', 'take_profit_pct', fallback='6.0')),
            'stop_loss_pct': float(self.bot_config.get('pre_match_trading', 'stop_loss_pct', fallback='4.0')),
            'min_odd': float(self.bot_config.get('pre_match_trading', 'min_odd', fallback='1.50')),
            'max_odd': float(self.bot_config.get('pre_match_trading', 'max_odd', fallback='3.50')),
            'min_hours_before_start': int(self.bot_config.get('pre_match_trading', 'min_hours_before_start', fallback='2')),
            'max_hours_before_start': int(self.bot_config.get('pre_match_trading', 'max_hours_before_start', fallback='48')),
            'min_market_volume': float(self.bot_config.get('pre_match_trading', 'min_market_volume', fallback='1000')),
            'close_before_start_minutes': int(self.bot_config.get('pre_match_trading', 'close_before_start_minutes', fallback='30')),
            'market_types': self.bot_config.get('pre_match_trading', 'market_types', fallback='MATCH_ODDS').split(','),
        }
        
        self.lay_draw_config = self._build_lay_draw_config()
        
        # Gestão de banca para Lay Draw
        self.lay_draw_daily_start_balance: Optional[float] = None
        self.lay_draw_initial_balance: Optional[float] = None
        self.lay_draw_last_day: Optional[int] = None
        self.lay_draw_paused_today: bool = False
        self.lay_draw_stopped_permanently: bool = False
        
        # API
        self.api = BetfairAPI(config_file)
        self.api.login()
        
        # Banco de dados
        self.db = BetDatabase()
        
        # Carregar apostas ativas do banco de dados
        self.active_bets: Dict[str, ActiveBet] = self.load_active_bets()
        self.bet_counter = 0
        # Controle de stop-loss: bet_ids que já tiveram LAY de stop-loss aplicado
        self._stop_loss_applied: set = set()
        # Controle de stop-loss parcial: bet_ids que já tiveram LAY Over 0.5 (meia perda) aplicado
        
        # Estatísticas
        self.stats = {
            'total_bets': 0,
            'profit_bets': 0,
            'loss_bets': 0,
            'total_profit': 0.0,
            'soccer_bets': 0,
            'hockey_bets': 0,
            'tennis_bets': 0,
        }
        
        logger.info("Bot inicializado")
        logger.info(f"Stake: R$ {self.stake:.2f}")
        logger.info(f"Máximo de apostas por esporte: {self.max_bets_per_sport}")
        if len(self.active_bets) > 0:
            active_count = sum(1 for b in self.active_bets.values() if b.status == BetStatus.ACTIVE)
            logger.info(f"✓ Carregadas {active_count} apostas ativas do arquivo de persistência")
        
        # Inicializar notificador do Telegram
        try:
            self.telegram = TelegramNotifier(bot_config_file)
            if self.telegram.enabled:
                logger.info("✓ Notificações do Telegram habilitadas")
        except Exception as e:
            logger.warning(f"Erro ao inicializar Telegram: {e}")
            self.telegram = None

    def _get_optional_float_config(self, section: str, option: str, fallback: Optional[float] = None) -> Optional[float]:
        """Lê um float opcional do INI; vazio vira None."""
        raw_value = self.bot_config.get(section, option, fallback='')
        if raw_value is None:
            return fallback
        value = str(raw_value).strip()
        if not value:
            return fallback
        try:
            return float(value)
        except (TypeError, ValueError):
            logger.warning(f"Configuração inválida para {section}.{option}='{raw_value}', usando fallback {fallback}")
            return fallback
    
    def reload_config(self):
        """Recarrega as configurações do arquivo bot_config.ini em tempo real"""
        try:
            # Reler o arquivo de configuração
            self.bot_config.read(self.bot_config_file)
            
            # Atualizar configurações do bot
            old_stake = self.stake
            old_max_bets = self.max_bets_per_sport
            old_check_interval = self.check_interval
            
            self.stake = float(self.bot_config.get('bot', 'stake', fallback='50.0'))
            self.max_bets_per_sport = int(self.bot_config.get('bot', 'max_bets_per_sport', fallback='10'))
            self.check_interval = int(self.bot_config.get('bot', 'check_interval', fallback='30'))
            
            # Atualizar configurações de futebol (Over 0.5 Gols)
            old_min_odd = self.soccer_config['min_odd']
            old_check_time = self.soccer_config['check_time_window']
            
            self.soccer_config['enabled'] = self.bot_config.getboolean('soccer', 'enabled', fallback=True)
            self.soccer_config['entry_min_minute'] = int(self.bot_config.get('soccer', 'entry_min_minute', fallback='1'))
            self.soccer_config['entry_max_minute'] = int(self.bot_config.get('soccer', 'entry_max_minute', fallback='45'))
            self.soccer_config['entry_goal_line'] = float(self.bot_config.get('soccer', 'entry_goal_line', fallback='1.5'))
            self.soccer_config['entry_odds_min'] = float(self.bot_config.get('soccer', 'entry_odds_min', fallback='1.80'))
            self.soccer_config['entry_odds_max'] = float(self.bot_config.get('soccer', 'entry_odds_max', fallback='2.20'))
            self.soccer_config['take_profit_pct'] = float(self.bot_config.get('soccer', 'take_profit_pct', fallback='1.5'))
            self.soccer_config['stop_loss_pct'] = float(self.bot_config.get('soccer', 'stop_loss_pct', fallback='10.0'))
            self.soccer_config['timeout_minutes'] = int(self.bot_config.get('soccer', 'timeout_minutes', fallback='10'))
            self.soccer_config['over_05_odds_min'] = float(self.bot_config.get('soccer', 'over_05_odds_min', fallback='1.20'))
            self.soccer_config['over_05_odds_max'] = float(self.bot_config.get('soccer', 'over_05_odds_max', fallback='1.50'))
            self.soccer_config['min_odd'] = float(self.bot_config.get('soccer', 'min_odd', fallback='2.15'))
            self.soccer_config['max_odd'] = self._get_optional_float_config('soccer', 'max_odd')
            self.soccer_config['under_25_min_odd'] = float(self.bot_config.get('soccer', 'under_25_min_odd', fallback='1.35'))
            self.soccer_config['under_25_max_odd'] = self._get_optional_float_config('soccer', 'under_25_max_odd')
            self.soccer_config['cs00_fallback_min_minute'] = int(self.bot_config.get('soccer', 'cs00_fallback_min_minute', fallback='88'))
            self.soccer_config['under_15_emergency_min_minute'] = int(self.bot_config.get('soccer', 'under_15_emergency_min_minute', fallback='93'))
            self.soccer_config['check_time_window'] = self.bot_config.getboolean('soccer', 'check_time_window', fallback=True)
            self.soccer_config['under_hedge_enabled'] = self.bot_config.getboolean('soccer', 'under_hedge_enabled', fallback=False)
            self.soccer_config['under_hedge_stake'] = float(self.bot_config.get('soccer', 'under_hedge_stake', fallback='15.0'))
            self.soccer_config['under_hedge_min_minute'] = int(self.bot_config.get('soccer', 'under_hedge_min_minute', fallback='73'))
            self.soccer_config['require_game_time_to_bet'] = self.bot_config.getboolean('soccer', 'require_game_time_to_bet', fallback=True)
            self.soccer_config['stop_loss_lay_enabled'] = self.bot_config.getboolean('soccer', 'stop_loss_lay_enabled', fallback=False)
            self.soccer_config['stop_loss_lay_threshold'] = float(self.bot_config.get('soccer', 'stop_loss_lay_threshold', fallback='2.0'))
            self.soccer_config['under_high_hedge_enabled'] = self.bot_config.getboolean('soccer', 'under_high_hedge_enabled', fallback=False)
            self.soccer_config['under_high_hedge_stake'] = float(self.bot_config.get('soccer', 'under_high_hedge_stake', fallback='15.0'))
            self.soccer_config['under_high_hedge_min_odd'] = float(self.bot_config.get('soccer', 'under_high_hedge_min_odd', fallback='1.15'))
            self.soccer_config['under_high_hedge_min_odd_first_entry'] = float(self.bot_config.get('soccer', 'under_high_hedge_min_odd_first_entry', fallback='1.08'))
            self.soccer_config['under_high_hedge_trigger_minute'] = int(self.bot_config.get('soccer', 'under_high_hedge_trigger_minute', fallback='40'))
            self.soccer_config['under_high_hedge_end_minute'] = int(self.bot_config.get('soccer', 'under_high_hedge_end_minute', fallback='88'))
            self.soccer_config['under_high_hedge_max_entries'] = int(self.bot_config.get('soccer', 'under_high_hedge_max_entries', fallback='2'))
            self.soccer_config['under_high_hedge_second_entry_minute'] = int(self.bot_config.get('soccer', 'under_high_hedge_second_entry_minute', fallback='60'))

            self.tennis_config['enabled'] = self.bot_config.getboolean('tennis', 'enabled', fallback=True)
            self.tennis_config['entry_min_odd'] = float(self.bot_config.get('tennis', 'entry_min_odd', fallback='1.80'))
            self.tennis_config['entry_max_odd'] = float(self.bot_config.get('tennis', 'entry_max_odd', fallback='2.20'))
            self.tennis_config['max_concurrent_bets'] = int(self.bot_config.get('tennis', 'max_concurrent_bets', fallback='7'))
            self.tennis_config['take_profit_pct'] = float(self.bot_config.get('tennis', 'take_profit_pct', fallback='3.0'))
            self.tennis_config['stop_loss_pct'] = float(self.bot_config.get('tennis', 'stop_loss_pct', fallback='10.0'))
            
            # Log apenas se houver mudanças
            if old_stake != self.stake:
                logger.info(f"🔄 Configuração atualizada: Stake R$ {old_stake:.2f} → R$ {self.stake:.2f}")
            if old_max_bets != self.max_bets_per_sport:
                logger.info(f"🔄 Configuração atualizada: Max Apostas {old_max_bets} → {self.max_bets_per_sport}")
            if old_check_interval != self.check_interval:
                logger.info(f"🔄 Configuração atualizada: Intervalo {old_check_interval}s → {self.check_interval}s")
            if old_min_odd != self.soccer_config['min_odd']:
                logger.info(f"🔄 Configuração atualizada: Min Odd {old_min_odd:.2f} → {self.soccer_config['min_odd']:.2f}")
            if old_check_time != self.soccer_config['check_time_window']:
                status = "Ligado" if self.soccer_config['check_time_window'] else "Desligado"
                logger.info(f"🔄 Configuração atualizada: Verificação de Tempo → {status}")
                
            self.lay_draw_config = self._build_lay_draw_config()
                
        except Exception as e:
            logger.warning(f"Erro ao recarregar configurações: {e}")

    def _build_lay_draw_config(self) -> Dict:
        """Lê configurações da estratégia Lay Draw do config file."""
        return {
            'enabled':              self.bot_config.getboolean('lay_draw', 'enabled', fallback=False),
            'min_odd':              float(self.bot_config.get('lay_draw', 'min_odd', fallback='2.8')),
            'max_odd':              float(self.bot_config.get('lay_draw', 'max_odd', fallback='3.5')),
            'take_profit_odd':      float(self.bot_config.get('lay_draw', 'take_profit_odd', fallback='4.5')),
            'stop_loss_odd':        float(self.bot_config.get('lay_draw', 'stop_loss_odd', fallback='2.2')),
            'entry_max_minute':     int(self.bot_config.get('lay_draw', 'entry_max_minute', fallback='15')),
            'exit_max_minute':      int(self.bot_config.get('lay_draw', 'exit_max_minute', fallback='45')),
            'stake_pct':            float(self.bot_config.get('lay_draw', 'stake_pct', fallback='2.0')),
            'max_concurrent_bets':  int(self.bot_config.get('lay_draw', 'max_concurrent_bets', fallback='3')),
            'min_market_volume':    float(self.bot_config.get('lay_draw', 'min_market_volume', fallback='5000')),
            'daily_loss_limit_pct': float(self.bot_config.get('lay_draw', 'daily_loss_limit_pct', fallback='10.0')),
            'total_loss_limit_pct': float(self.bot_config.get('lay_draw', 'total_loss_limit_pct', fallback='20.0')),
            'commission':           float(self.bot_config.get('lay_draw', 'commission', fallback='5.0')),
            # Fechar só quando positivo (take profit). Se False, não faz stop loss nem timeout.
            'enable_stop_loss':     self.bot_config.getboolean('lay_draw', 'enable_stop_loss', fallback=False),
            'enable_timeout_exit':  self.bot_config.getboolean('lay_draw', 'enable_timeout_exit', fallback=False),
            # Stop loss só dispara se o prejuízo for >= este valor (em R$). Ex.: 5 = só fecha se perder 5+ reais.
            'stop_loss_min_loss_brl': float(self.bot_config.get('lay_draw', 'stop_loss_min_loss_brl', fallback='5.0')),
        }

    def load_active_bets(self) -> Dict[str, ActiveBet]:
        """Carrega apostas ativas do banco de dados"""
        try:
            bets_data = self.db.get_active_bets()
            active_bets = {}
            
            for bet_data in bets_data:
                # Converter strings de data de volta para datetime
                if 'entry_time' in bet_data and isinstance(bet_data['entry_time'], str):
                    bet_data['entry_time'] = datetime.fromisoformat(bet_data['entry_time'])
                
                # Converter string de sport de volta para enum
                if 'sport' in bet_data and isinstance(bet_data['sport'], str):
                    # Extrair apenas o nome do enum (ex: "SportType.SOCCER" -> "SOCCER")
                    sport_name = bet_data['sport'].split('.')[-1] if '.' in bet_data['sport'] else bet_data['sport']
                    bet_data['sport'] = SportType[sport_name]
                
                # Converter string de status de volta para enum
                if 'status' in bet_data and isinstance(bet_data['status'], str):
                    status_name = bet_data['status'].split('.')[-1] if '.' in bet_data['status'] else bet_data['status']
                    bet_data['status'] = BetStatus[status_name]
                
                # Filtrar apenas campos que existem na classe ActiveBet
                import dataclasses
                active_bet_fields = {f.name for f in dataclasses.fields(ActiveBet)}
                filtered_bet_data = {k: v for k, v in bet_data.items() if k in active_bet_fields}
                
                active_bets[bet_data['bet_id']] = ActiveBet(**filtered_bet_data)
            
            logger.info(f"Carregadas {len(active_bets)} apostas ativas do banco de dados")
            return active_bets
        except Exception as e:
            logger.error(f"Erro ao carregar apostas do banco de dados: {e}")
            return {}
    
    def save_active_bets(self):
        """Salva apostas ativas no banco de dados"""
        # Método mantido por compatibilidade, mas agora as apostas são salvas
        # individualmente quando criadas/atualizadas
        pass
    
    def get_sport_id(self, sport: SportType) -> str:
        """Retorna o ID do esporte na Betfair"""
        sport_ids = {
            SportType.SOCCER: "1",
            SportType.ICE_HOCKEY: "2",
            SportType.TENNIS: "2",
        }
        return sport_ids.get(sport, "1")
    
    def _create_search_variations_over_05(self, goals_val=0.5):
        """Gera variações do valor 0.5 para busca no nome do runner Over 0.5."""
        goals_str = str(goals_val)
        variations = [goals_str, goals_str.replace(".", ""), goals_str.replace(".", " "), goals_str.replace(".", ",")]
        if goals_str.endswith(".5"):
            whole_part = goals_str.replace(".5", "")
            variations.extend([f"{whole_part}½", f"{whole_part} ½"])
        return variations

    def _market_type_code_for_goal_line(self, goals_val: float) -> str:
        mapping = {
            0.5: 'OVER_UNDER_05',
            1.5: 'OVER_UNDER_15',
            2.5: 'OVER_UNDER_25',
            3.5: 'OVER_UNDER_35',
            4.5: 'OVER_UNDER_45',
            5.5: 'OVER_UNDER_55',
            6.5: 'OVER_UNDER_65',
        }
        return mapping.get(float(goals_val), 'OVER_UNDER_15')

    def _get_over_runner(self, runners, goals_val=0.5):
        """Encontra o runner Over X.5 Goals (não Under)."""
        for r in runners or []:
            runner_name = (r.get("runnerName") or "").upper()
            if "UNDER" in runner_name or "ABAIXO" in runner_name:
                continue
            if "OVER" not in runner_name and "ACIMA" not in runner_name:
                continue
            for v in self._create_search_variations_over_05(goals_val):
                if v.upper() in runner_name or v in runner_name:
                    return r
        return None

    def _get_over_05_runner(self, runners):
        """Encontra o runner Over 0.5 Goals (não Under!). Over 0.5 = odd baixa (1.01-1.50)."""
        return self._get_over_runner(runners, 0.5)

    def _find_under_market(
        self,
        event_id: str,
        under_type_codes: List[str],
        goals_map: Dict[str, float],
        hedge_min_odd: float,
        hedge_max_odd: Optional[float],
        hedge_stake: float,
        label: str,
    ) -> Optional[Dict]:
        event_id_str = str(event_id)

        try:
            all_markets = []
            for inplay_flag in [True, False]:
                try:
                    result = self.api.list_market_catalogue(
                        filter_dict={
                            'eventTypeIds': ['1'],
                            'marketTypeCodes': under_type_codes,
                            'inPlayOnly': inplay_flag,
                        },
                        market_projection=['MARKET_DESCRIPTION', 'RUNNER_DESCRIPTION', 'EVENT'],
                        max_results=200
                    ) or []
                    all_markets.extend(result)
                    if result:
                        break
                except Exception as e:
                    logger.debug(f"{label}: erro ao buscar mercados Under (inplay={inplay_flag}): {e}")

            if not all_markets:
                logger.debug(f"{label}: API retornou vazio para markets do evento {event_id}")
                logger.debug(f"{label}: nenhum mercado encontrado para evento {event_id}")
                return None

            event_markets = [
                m for m in all_markets
                if str(m.get('event', {}).get('id', '')) == event_id_str
            ]
            logger.debug(f"{label}: {len(all_markets)} mercados encontrados, {len(event_markets)} para evento {event_id}")

            if not event_markets:
                logger.debug(f"{label}: nenhum mercado encontrado para evento {event_id}")
                return None

            market_ids = [m.get('marketId') for m in event_markets if m.get('marketId')]
            try:
                books = self.api.list_market_book(
                    market_ids=market_ids,
                    price_projection={'priceData': ['EX_BEST_OFFERS']}
                ) or []
            except Exception as e:
                logger.debug(f"{label}: erro ao buscar books: {e}")
                return None

            books_by_id = {b.get('marketId'): b for b in books}
            catalogue_by_id = {m.get('marketId'): m for m in event_markets}

            for market_type_code in under_type_codes:
                goals_val = goals_map[market_type_code]
                goals_variations = self._create_search_variations_over_05(goals_val)

                for market in event_markets:
                    market_id = market.get('marketId')
                    mtype = market.get('description', {}).get('marketType', '')
                    if mtype != market_type_code:
                        continue

                    book = books_by_id.get(market_id)
                    if not book or book.get('status') != 'OPEN':
                        continue

                    catalogue_runners = catalogue_by_id.get(market_id, {}).get('runners', [])
                    book_runners = book.get('runners', [])

                    under_selection_id = None
                    for cr in catalogue_runners:
                        r_name = (cr.get('runnerName') or '').upper()
                        if 'UNDER' not in r_name and 'ABAIXO' not in r_name and 'MENOS' not in r_name:
                            continue
                        for v in goals_variations:
                            if v.upper() in r_name or v in r_name:
                                under_selection_id = cr.get('selectionId') or cr.get('id')
                                break
                        if under_selection_id:
                            break

                    if not under_selection_id:
                        if len(catalogue_runners) == 2:
                            ids = [cr.get('selectionId') or cr.get('id') for cr in catalogue_runners]
                            under_selection_id = max(ids) if ids else None
                        if not under_selection_id:
                            logger.debug(f"{label}: runner não encontrado em {market_id}")
                            continue

                    under_book_runner = None
                    for br in book_runners:
                        bid = br.get('selectionId') or br.get('id')
                        try:
                            if int(bid) == int(under_selection_id):
                                under_book_runner = br
                                break
                        except (ValueError, TypeError):
                            continue

                    if not under_book_runner:
                        continue

                    avail_back = under_book_runner.get('ex', {}).get('availableToBack', [])
                    if not avail_back:
                        continue

                    price = avail_back[0].get('price', 0)
                    size = avail_back[0].get('size', 0)

                    if price < max(1.01, hedge_min_odd):
                        continue
                    if hedge_max_odd and price > hedge_max_odd:
                        continue
                    if size < hedge_stake:
                        continue

                    market_name = market.get('marketName', f'Under {goals_val} Goals')
                    logger.info(f"  🛡️ {label} encontrado: {market_name} | Odd: {price:.2f} | Evento {event_id}")
                    return {
                        'market_id': market_id,
                        'selection_id': int(under_selection_id),
                        'price': price,
                        'market_name': market_name,
                        'goals_val': goals_val,
                    }

            logger.debug(f"{label}: nenhum mercado elegível encontrado para evento {event_id}")
            return None
        except Exception as e:
            logger.error(f"Erro ao buscar {label} para evento {event_id}: {e}")
            return None

    def find_best_under_market(self, event_id: str, min_odd_override: Optional[float] = None) -> Optional[Dict]:
        """Encontra o mercado Under 1.5 (aposentado)."""
        # Estratégia Under 1.5 foi retirada; nunca mais retornamos mercados para ela.
        logger.info("🛑 find_best_under_market: Under 1.5 aposentado — retornando None.")
        return None

    def find_under_25_market(self, event_id: str, min_odd_override: Optional[float] = None) -> Optional[Dict]:
        """Encontra o mercado Under 2.5 disponível para um evento."""
        return self._find_under_market(
            event_id=event_id,
            under_type_codes=['OVER_UNDER_25'],
            goals_map={'OVER_UNDER_25': 2.5},
            hedge_min_odd=min_odd_override if min_odd_override is not None else self.soccer_config.get('under_25_min_odd', 1.35),
            hedge_max_odd=self.soccer_config.get('under_25_max_odd', None),
            hedge_stake=self.soccer_config.get('under_hedge_stake', self.stake),
            label='Hedge Under 2.5',
        )

    def find_under_high_market(self, event_id: str, min_odd_override: Optional[float] = None) -> Optional[Dict]:
        """
        Encontra o melhor mercado Under 5.5 / 4.5 / 6.5 para um evento.
        Prioriza Under 5.5 > 4.5 > 6.5.
        Usa under_high_hedge_min_odd como mínimo (ou min_odd_override para 1ª entrada).
        Retorna dict com market_id, selection_id, price, market_name, goals_val ou None.
        """
        under_type_codes = ['OVER_UNDER_55', 'OVER_UNDER_45', 'OVER_UNDER_65']
        goals_map = {'OVER_UNDER_45': 4.5, 'OVER_UNDER_55': 5.5, 'OVER_UNDER_65': 6.5}
        event_id_str = str(event_id)
        hedge_min_odd = min_odd_override if min_odd_override is not None else self.soccer_config.get('under_high_hedge_min_odd', 1.08)
        hedge_stake = self.soccer_config.get('under_high_hedge_stake', self.stake)

        try:
            all_markets = []
            for inplay_flag in [True, False]:
                try:
                    result = self.api.list_market_catalogue(
                        filter_dict={
                            'eventTypeIds': ['1'],
                            'eventIds': [event_id_str],
                            'marketTypeCodes': under_type_codes,
                            'inPlayOnly': inplay_flag,
                        },
                        market_projection=['MARKET_DESCRIPTION', 'RUNNER_DESCRIPTION', 'EVENT'],
                        max_results=50
                    ) or []
                    all_markets.extend(result)
                    if result:
                        break
                except Exception as e:
                    logger.debug(f"Under Alta: erro ao buscar mercados (inplay={inplay_flag}): {e}")

            if not all_markets:
                logger.debug(f"Under Alta: API retornou vazio para evento {event_id}")
                return None

            event_markets = [
                m for m in all_markets
                if str(m.get('event', {}).get('id', '')) == event_id_str
            ]
            if not event_markets:
                logger.debug(f"Under Alta: nenhum mercado para evento {event_id}")
                return None

            market_ids = [m.get('marketId') for m in event_markets if m.get('marketId')]
            try:
                books = self.api.list_market_book(
                    market_ids=market_ids,
                    price_projection={'priceData': ['EX_BEST_OFFERS']}
                ) or []
            except Exception as e:
                logger.debug(f"Under Alta: erro ao buscar books: {e}")
                return None

            books_by_id = {b.get('marketId'): b for b in books}
            catalogue_by_id = {m.get('marketId'): m for m in event_markets}

            # Prioriza Under pela ordem: 5.5 > 4.5 > 6.5
            for market_type_code in under_type_codes:
                goals_val = goals_map[market_type_code]
                goals_variations = self._create_search_variations_over_05(goals_val)

                for market in event_markets:
                    market_id = market.get('marketId')
                    mtype = market.get('description', {}).get('marketType', '')
                    if mtype != market_type_code:
                        continue

                    book = books_by_id.get(market_id)
                    if not book or book.get('status') != 'OPEN':
                        continue

                    catalogue_runners = catalogue_by_id.get(market_id, {}).get('runners', [])
                    book_runners = book.get('runners', [])

                    under_selection_id = None
                    for cr in catalogue_runners:
                        r_name = (cr.get('runnerName') or '').upper()
                        if 'UNDER' not in r_name and 'ABAIXO' not in r_name and 'MENOS' not in r_name:
                            continue
                        for v in goals_variations:
                            if v.upper() in r_name or v in r_name:
                                under_selection_id = cr.get('selectionId') or cr.get('id')
                                break
                        if under_selection_id:
                            break

                    if not under_selection_id:
                        if len(catalogue_runners) == 2:
                            ids = [cr.get('selectionId') or cr.get('id') for cr in catalogue_runners]
                            under_selection_id = max(ids) if ids else None
                        if not under_selection_id:
                            continue

                    under_book_runner = None
                    for br in book_runners:
                        bid = br.get('selectionId') or br.get('id')
                        try:
                            if int(bid) == int(under_selection_id):
                                under_book_runner = br
                                break
                        except (ValueError, TypeError):
                            continue

                    if not under_book_runner:
                        continue

                    avail_back = under_book_runner.get('ex', {}).get('availableToBack', [])
                    if not avail_back:
                        continue

                    price = avail_back[0].get('price', 0)
                    size = avail_back[0].get('size', 0)

                    if price < max(1.01, hedge_min_odd):
                        continue
                    if size < hedge_stake:
                        continue

                    market_name = market.get('marketName', f'Under {goals_val} Goals')
                    logger.info(f"  🛡️ Under Alta encontrado: {market_name} | Odd: {price:.2f} | Evento {event_id}")
                    return {
                        'market_id': market_id,
                        'selection_id': int(under_selection_id),
                        'price': price,
                        'market_name': market_name,
                        'goals_val': goals_val,
                    }

            logger.debug(f"Under Alta: nenhum mercado elegível (4.5/5.5/6.5) para evento {event_id}")
            return None
        except Exception as e:
            logger.error(f"Erro ao buscar Under Alta para evento {event_id}: {e}")
            return None

    def find_live_soccer_matches(self) -> List[Dict]:
        """Encontra partidas com mercado Over/Under configurado para a estratégia de futebol."""
        try:
            goal_line = self.soccer_config.get('entry_goal_line', 1.5)
            market_type_codes = [self._market_type_code_for_goal_line(goal_line)]
            logger.info("🔍 Buscando Over %.1f Gols (in-play + pré-live)...", goal_line)
            logger.info("📋 Market Type Codes: %s", market_type_codes)
            
            pre_match_enabled = self.soccer_config.get('pre_match_enabled', True)
            check_time_window = self.soccer_config.get('check_time_window', True)
            
            markets_inplay = []
            markets_upcoming = []
            
            # Buscar in-play e pré-live
            try:
                markets_inplay = self.api.list_market_catalogue(
                    filter_dict={
                        'eventTypeIds': ['1'],
                        'marketTypeCodes': market_type_codes,
                        'inPlayOnly': True,
                    },
                    market_projection=['MARKET_DESCRIPTION', 'RUNNER_DESCRIPTION', 'EVENT', 'MARKET_START_TIME'],
                    max_results=100
                ) or []
                markets_upcoming = self.api.list_market_catalogue(
                    filter_dict={
                        'eventTypeIds': ['1'],
                        'marketTypeCodes': market_type_codes,
                        'inPlayOnly': False,
                    },
                    market_projection=['MARKET_DESCRIPTION', 'RUNNER_DESCRIPTION', 'EVENT', 'MARKET_START_TIME'],
                    max_results=100
                ) or []
            except Exception as e:
                logger.warning("⚠️ listMarketCatalogue: %s", e)
                return []
            
            seen_ids = set()
            markets = []
            for m in markets_inplay:
                mid = m.get('marketId')
                if mid and mid not in seen_ids:
                    seen_ids.add(mid)
                    m['_is_inplay'] = True
                    markets.append(m)
            for m in markets_upcoming:
                mid = m.get('marketId')
                if mid and mid not in seen_ids:
                    seen_ids.add(mid)
                    m['_is_inplay'] = False
                    markets.append(m)
            
            logger.info("📊 Total mercados Over/Under %.1f: %d in-play + %d pré-live", goal_line, len(markets_inplay), len(markets_upcoming))
            
            valid_matches = []
            markets_filtered = 0
            seen_events = set()
            
            for market in markets:
                event = market.get('event', {})
                event_id = event.get('id')
                event_name = event.get('name', '')
                market_name = market.get('marketName', '')
                market_id = market.get('marketId')
                
                if not market_id or not event_id or event_id in seen_events:
                    markets_filtered += 1
                    continue
                
                over_runner = self._get_over_runner(market.get('runners', []), goal_line)
                if not over_runner:
                    markets_filtered += 1
                    logger.debug("  ❌ '%s' - runner Over %.1f não encontrado - pulando", market_name, goal_line)
                    continue
                
                runner_id = over_runner.get('selectionId') or over_runner.get('id') or over_runner.get('runnerId')
                if runner_id and isinstance(runner_id, str):
                    try:
                        runner_id = int(runner_id)
                    except (ValueError, TypeError):
                        markets_filtered += 1
                        continue
                if not runner_id:
                    markets_filtered += 1
                    continue
                
                seen_events.add(event_id)
                is_pre_match = not market.get('_is_inplay', False)
                market_start_time = market.get('marketStartTime')
                logger.info("  ✓ '%s' → Over %.1f para %s | startTime: %s", market_name, goal_line, event_name, market_start_time or 'N/D')
                valid_matches.append({
                    'market_id': market_id,
                    'event_id': event_id,
                    'event_name': event_name,
                    'market': market,
                    'entry_runner_id': runner_id,
                    'entry_runner_name': over_runner.get('runnerName', ''),
                    'is_pre_match': is_pre_match,
                    'market_start_time': market_start_time,
                })
            
            logger.info("📊 Resumo: %d mercados | %d filtrados | %d candidatos Over %.1f", len(markets), markets_filtered, len(valid_matches), goal_line)
            if not valid_matches and markets:
                logger.warning("⚠️ Nenhum jogo com Over %.1f disponível no momento.", goal_line)
            
            return valid_matches
        except Exception as e:
            logger.error(f"Erro ao buscar partidas de futebol: {e}")
            return []
    
    def find_live_hockey_matches(self) -> List[Dict]:
        """Encontra partidas de hóquei ao vivo"""
        try:
            filter_dict = {
                'eventTypeIds': ['2'],  # Ice Hockey
                'marketTypeCodes': ['TOTAL_GOALS'],
                'inPlay': True,
            }
            
            markets = self.api.list_market_catalogue(
                filter_dict=filter_dict,
                market_projection=['MARKET_DESCRIPTION', 'RUNNER_DESCRIPTION', 'EVENT'],
                max_results=100
            )
            
            valid_matches = []
            for market in markets:
                event = market.get('event', {})
                market_name = market.get('marketName', '')
                
                # Procurar por mercados de período
                if '1ST PERIOD' in market_name.upper() or 'PERIOD' in market_name.upper():
                    market_id = market.get('marketId')
                    if market_id:
                        valid_matches.append({
                            'market_id': market_id,
                            'event_id': event.get('id'),
                            'event_name': event.get('name', ''),
                            'market': market
                        })
            
            return valid_matches
        except Exception as e:
            logger.error(f"Erro ao buscar partidas de hóquei: {e}")
            return []
    
    def find_live_tennis_matches(self) -> List[Dict]:
        """Encontra partidas de tênis ao vivo"""
        try:
            entry_min_odd = self.tennis_config.get('entry_min_odd', 1.80)
            entry_max_odd = self.tennis_config.get('entry_max_odd', 2.20)
            filter_dict = {
                'eventTypeIds': ['2'],  # Tennis
                'marketTypeCodes': ['MATCH_ODDS'],
                'inPlay': True,
            }
            
            markets = self.api.list_market_catalogue(
                filter_dict=filter_dict,
                market_projection=['MARKET_DESCRIPTION', 'RUNNER_DESCRIPTION', 'EVENT'],
                max_results=100
            )
            
            valid_matches = []
            for market in markets:
                event = market.get('event', {})
                runners = market.get('runners', [])
                
                # Encontrar o favorito (menor odd)
                if len(runners) >= 2:
                    # Obter odds atuais
                    market_id = market.get('marketId')
                    if market_id:
                        market_book = self.api.list_market_book(
                            market_ids=[market_id],
                            price_projection={'priceData': ['EX_BEST_OFFERS']}
                        )
                        
                        if market_book:
                            runners_data = market_book[0].get('runners', [])
                            if runners_data:
                                # Encontrar menor odd (favorito)
                                favorite = min(runners_data, 
                                             key=lambda r: r.get('ex', {}).get('availableToBack', [{}])[0].get('price', 999))
                                favorite_odd = favorite.get('ex', {}).get('availableToBack', [{}])[0].get('price', 999)
                                
                                if entry_min_odd <= favorite_odd <= entry_max_odd:
                                    valid_matches.append({
                                        'market_id': market_id,
                                        'event_id': event.get('id'),
                                        'event_name': event.get('name', ''),
                                        'favorite_runner': favorite,
                                        'favorite_odd': favorite_odd,
                                        'market': market
                                    })
            
            return valid_matches
        except Exception as e:
            logger.error(f"Erro ao buscar partidas de tênis: {e}")
            return []
    
    def get_match_time(self, market_id: str) -> Optional[int]:
        """Obtém o tempo de jogo em minutos (aproximado) baseado no tempo decorrido desde o início do mercado"""
        try:
            # Buscar informações do mercado para obter o horário de início
            filter_dict = {
                'marketIds': [market_id]
            }
            
            markets = self.api.list_market_catalogue(
                filter_dict=filter_dict,
                market_projection=['MARKET_START_TIME', 'EVENT'],
                max_results=1
            )
            
            if not markets or len(markets) == 0:
                logger.debug(f"Mercado {market_id}: Não encontrado no catálogo")
                return None
            
            market = markets[0]
            market_start_time_str = market.get('marketStartTime')
            
            if not market_start_time_str:
                logger.debug(f"Mercado {market_id}: Sem horário de início")
                return None
            
            # Converter para datetime (formato ISO 8601 da Betfair: "2024-01-20T15:30:00.000Z")
            try:
                # Normaliza o string: remove milissegundos e garante timezone UTC
                # Ex: "2024-01-20T15:30:00.000Z" → "2024-01-20T15:30:00+00:00"
                time_str = market_start_time_str.strip()
                # Remover milissegundos antes do Z ou do +
                if '.' in time_str:
                    dot_idx = time_str.index('.')
                    tz_part = ''
                    if '+' in time_str[dot_idx:]:
                        tz_part = '+' + time_str[dot_idx:].split('+', 1)[1]
                    elif time_str.endswith('Z'):
                        tz_part = '+00:00'
                    time_str = time_str[:dot_idx] + tz_part
                elif time_str.endswith('Z'):
                    time_str = time_str[:-1] + '+00:00'

                # Tentar parse ISO format
                try:
                    market_start_time = datetime.fromisoformat(time_str)
                except ValueError:
                    # Fallback: parse manual para "2024-01-20T15:30:00" sem timezone
                    if 'T' in time_str:
                        date_part, time_part = time_str.split('T', 1)
                        time_part = time_part.split('+')[0].split('-')[0]
                        year, month, day = date_part.split('-')
                        parts = time_part.split(':')
                        hour = int(parts[0])
                        minute = int(parts[1])
                        second = int(float(parts[2])) if len(parts) > 2 else 0
                        second = max(0, min(59, second))
                        market_start_time = datetime(
                            int(year), int(month), int(day),
                            hour, minute, second,
                            tzinfo=timezone.utc
                        )
                    else:
                        raise ValueError(f"Formato de data não reconhecido: {time_str}")
                
                # Obter tempo atual (com timezone se o market_start_time tiver)
                if market_start_time.tzinfo:
                    now = datetime.now(market_start_time.tzinfo)
                else:
                    now = datetime.now()
                
                # Calcular tempo decorrido em minutos
                elapsed = (now - market_start_time).total_seconds() / 60

                # Descontar o intervalo (~15 min) se o jogo já passou do 1º tempo
                # O relógio de parede conta o intervalo mas o relógio do jogo não
                HALFTIME_DURATION = 15
                if elapsed > 45 + HALFTIME_DURATION:
                    elapsed -= HALFTIME_DURATION

                # Retornar apenas se o jogo já começou (tempo positivo)
                if elapsed > 0:
                    return int(elapsed)
                else:
                    logger.debug(f"Mercado {market_id}: Jogo ainda não começou (tempo: {elapsed:.1f} min)")
                    return None
                    
            except Exception as e:
                logger.debug(f"Erro ao calcular tempo do jogo {market_id}: {e}")
                return None
                
        except Exception as e:
            logger.debug(f"Erro ao obter tempo de jogo para {market_id}: {e}")
            return None
    
    def get_match_score(self, market_id: str) -> Optional[Dict[str, int]]:
        """Obtém o placar via In-Play Service da Betfair quando disponível."""
        try:
            filter_dict = {
                'marketIds': [market_id]
            }
            markets = self.api.list_market_catalogue(
                filter_dict=filter_dict,
                market_projection=['EVENT'],
                max_results=1
            )
            if not markets:
                return None

            event_id = str(markets[0].get('event', {}).get('id', ''))
            if not event_id:
                return None

            scores = get_inplay_scores(
                [event_id],
                session_token=self.api.session_token,
                app_key=self.api.app_key
            )
            score = scores.get(event_id)
            if not score:
                return None

            home_score = int(score.get('home'))
            away_score = int(score.get('away'))
            return {
                'home': home_score,
                'away': away_score,
                'total': home_score + away_score,
                'status': score.get('status', ''),
            }
        except Exception as e:
            logger.debug(f"Erro ao obter placar para {market_id}: {e}")
            return None

    def _extract_score_status_minute(self, score_status: str) -> Optional[int]:
        """Extrai o minuto do status do placar do In-Play Service, ex: '73'' -> 73."""
        try:
            if not score_status:
                return None
            m = re.search(r'(\d{1,3})', str(score_status))
            if not m:
                return None
            return int(m.group(1))
        except Exception:
            return None

    def _is_second_half(self, game_minute: Optional[int], score_status: str = '') -> bool:
        """Considera 2º tempo pelo minuto, ou por status textual quando disponível."""
        try:
            if game_minute is not None and game_minute >= 46:
                return True
            status = (score_status or '').strip().lower()
            if any(token in status for token in ('2h', '2nd', 'second half', 'segundo tempo', '2º')):
                return True
        except Exception:
            pass
        return False

    def get_live_match_minute(self, market_id: str, score: Optional[Dict[str, int]] = None) -> Optional[int]:
        """
        Usa primeiro o minuto oficial do feed de placar.
        Se não vier minuto confiável no placar, cai para o cálculo aproximado por relógio.
        """
        try:
            live_score = score if score is not None else self.get_match_score(market_id)
            if live_score:
                score_status_minute = self._extract_score_status_minute(live_score.get('status', ''))
                if score_status_minute is not None:
                    return score_status_minute
        except Exception:
            pass
        return self.get_match_time(market_id)
    
    def check_soccer_entry_conditions(self, market_id: str, entry_runner_id: int = None, is_pre_match: bool = False) -> Optional[Dict]:
        """Verifica condições de entrada para o mercado Over configurado no futebol."""
        try:
            goal_line = self.soccer_config.get('entry_goal_line', 1.5)
            market_book = self.api.list_market_book(
                market_ids=[market_id],
                price_projection={'priceData': ['EX_BEST_OFFERS']}
            )
            
            if not market_book:
                logger.debug(f"Mercado {market_id}: Sem dados de mercado")
                return None
            
            market = market_book[0]
            
            market_status = market.get('status')
            if market_status != 'OPEN':
                logger.debug(f"Mercado {market_id}: Status {market_status} (não está aberto - precisa ser OPEN)")
                return None
            
            runners = market.get('runners', [])
            if not runners:
                logger.debug(f"Mercado {market_id}: Sem runners")
                return None
            
            # Encontrar runner Over da linha configurada pelo ID ou pelo nome
            over_runner = None
            if entry_runner_id:
                for runner in runners:
                    runner_id = runner.get('id') or runner.get('selectionId')
                    try:
                        if int(runner_id) == int(entry_runner_id):
                            over_runner = runner
                            logger.debug(f"Mercado {market_id}: Runner Over {goal_line:.1f} encontrado por ID: {entry_runner_id}")
                            break
                    except (ValueError, TypeError):
                        continue
            
            if not over_runner:
                over_runner = self._get_over_runner(runners, goal_line)
                if over_runner:
                    logger.debug(f"Mercado {market_id}: Runner Over {goal_line:.1f} encontrado por nome")
            
            if not over_runner:
                runner_info = [f"ID:{r.get('id') or r.get('selectionId')} Name:{r.get('runnerName', 'N/A')}" for r in runners]
                logger.debug(f"Mercado {market_id}: Runner Over {goal_line:.1f} não encontrado. Runners: {', '.join(runner_info)}")
                return None
            
            available_to_back = over_runner.get('ex', {}).get('availableToBack', [])
            if not available_to_back or len(available_to_back) == 0:
                logger.debug(f"Mercado {market_id}: Sem odds disponíveis para BACK Over {goal_line:.1f}")
                return None
            
            current_price = available_to_back[0].get('price', 0)
            available_size = available_to_back[0].get('size', 0)
            
            if current_price == 0 or current_price < 1.01:
                logger.debug(f"Mercado {market_id}: Preço inválido: {current_price}")
                return None
            
            min_odd = self.soccer_config.get('entry_odds_min', 1.80)
            max_odd = self.soccer_config.get('entry_odds_max', 2.20)
            if current_price < min_odd:
                logger.info(f"💰 Mercado {market_id}: Odd Over {goal_line:.1f} muito baixa ({current_price:.2f} < {min_odd:.2f})")
                return None
            if current_price > max_odd:
                logger.info(f"🚫 Mercado {market_id}: Odd Over {goal_line:.1f} fora da faixa ({current_price:.2f} > {max_odd:.2f}) - recusado")
                return None
            
            # Verificar liquidez suficiente
            if available_size < self.stake:
                logger.info(f"⚠️ Mercado {market_id}: Liquidez insuficiente: {available_size:.2f} < {self.stake:.2f}")
                return None
            
            # ✅ Verificar se já temos aposta ativa neste mercado (na memória)
            for bet in self.active_bets.values():
                if bet.market_id == market_id and bet.status == BetStatus.ACTIVE:
                    logger.info(f"⚠️ Mercado {market_id}: Já tem aposta ativa na memória (Bet ID: {bet.bet_id})")
                    return None
            
            # ✅ Verificar se já existe aposta ativa no banco de dados (mesmo que não esteja na memória)
            # Também verificar por event_id para evitar 2 apostas no mesmo jogo
            try:
                db_active_bets = self.db.get_active_bets()
                for db_bet in db_active_bets:
                    if db_bet.get('market_id') == market_id and db_bet.get('status') == 'ACTIVE':
                        db_bet_id = db_bet.get('bet_id', 'N/A')
                        logger.info(f"⚠️ Mercado {market_id}: Já tem aposta ativa no banco de dados (Bet ID: {db_bet_id})")
                        return None
                    # Verificar também por event_id (evitar 2 apostas no mesmo jogo)
                    # Nota: event_id precisa ser passado como parâmetro, então vamos verificar depois
            except Exception as e:
                logger.debug(f"Erro ao verificar banco de dados para mercado {market_id}: {e}")
            
            # ✅ Verificar se já existe aposta ativa na Betfair API (mesmo após reinício do container)
            try:
                current_orders = self.api.list_current_orders()
                if current_orders and 'currentOrders' in current_orders:
                    for order in current_orders['currentOrders']:
                        order_market_id = order.get('marketId')
                        order_status = order.get('status')
                        order_size_matched = order.get('sizeMatched', 0)
                        
                        # Verificar se é o mesmo mercado e se a aposta foi executada
                        if order_market_id == market_id and order_status == 'EXECUTION_COMPLETE' and order_size_matched > 0:
                            order_bet_id = order.get('betId', 'N/A')
                            logger.info(f"⚠️ Mercado {market_id}: Já existe aposta ativa na Betfair (Bet ID: {order_bet_id}) - evitando duplicata")
                            return None
            except Exception as e:
                logger.debug(f"Erro ao verificar apostas ativas na Betfair para mercado {market_id}: {e}")
                # Continuar mesmo se houver erro na verificação da API
            
            # Futebol não usa limite de quantidade; o contador fica só para diagnóstico.
            soccer_bets_count = sum(1 for b in self.active_bets.values() 
                                  if b.sport == SportType.SOCCER and b.status == BetStatus.ACTIVE)
            logger.debug(f"Mercado {market_id}: apostas ativas de futebol no momento: {soccer_bets_count}")
            
            # Verificar saldo disponível antes de fazer aposta BACK
            # BACK: precisa apenas do stake (não precisa calcular liability)
            balance = self.get_account_balance()
            if balance:
                if balance['available'] < self.stake:
                    logger.warning(f"⚠️ Mercado {market_id}: Saldo insuficiente. Disponível: R$ {balance['available']:.2f}, Necessário: R$ {self.stake:.2f}")
                    return None
            else:
                logger.warning(f"⚠️ Mercado {market_id}: Não foi possível verificar saldo")
                return None
            
            # ✅ VERIFICAR SE É PRÉ-JOGO OU AO VIVO
            pre_match_enabled = self.soccer_config.get('pre_match_enabled', False)
            check_time_window = self.soccer_config.get('check_time_window', False)
            match_time = None  # Inicializar variável
            
            if pre_match_enabled:
                # Estratégia pré-jogo ativada
                if is_pre_match:
                    # Mercado é pré-jogo: verificar se o jogo ainda não começou
                    match_time = self.get_match_time(market_id)
                    if match_time is None:
                        # Se não conseguir obter o tempo, assumir que o jogo ainda não começou (pré-jogo)
                        logger.info(f"🎯 Mercado {market_id}: Modo PRÉ-JOGO - assumindo que jogo ainda não começou - PERMITINDO aposta")
                        match_time = -1  # Marcar como pré-jogo
                    elif match_time < 0:
                        # Tempo negativo = jogo ainda não começou (agendado para o futuro) - OK para pré-jogo
                        logger.info(f"🎯 Mercado {market_id}: Modo PRÉ-JOGO - jogo ainda não começou (tempo: {match_time:.1f} min) - PERMITINDO aposta")
                    else:
                        # Tempo positivo = jogo já começou - BLOQUEAR aposta pré-jogo
                        logger.info(f"🎯 Mercado {market_id}: Modo PRÉ-JOGO - jogo já começou ({match_time} min) - BLOQUEANDO aposta (só aceita pré-jogo)")
                        return None
                else:
                    # Mercado é ao vivo (fallback): verificar janela de tempo se check_time_window estiver ativo
                    if check_time_window:
                        logger.info(f"⏱️ Mercado {market_id}: Fallback AO VIVO - verificando janela de tempo...")
                        match_time = self.get_match_time(market_id)
                        if match_time is None:
                            # Se não conseguir obter o tempo, assumir que o jogo ainda não começou
                            logger.info(f"⏱️ Mercado {market_id}: Não foi possível obter tempo de jogo - assumindo que jogo ainda não começou (agendado) - PERMITINDO aposta")
                            # Continuar com a aposta (não bloquear)
                        elif match_time < 0:
                            # Tempo negativo = jogo ainda não começou (agendado para o futuro)
                            logger.info(f"⏱️ Mercado {market_id}: Jogo ainda não começou (tempo negativo: {match_time:.1f} min) - PERMITINDO aposta")
                            # Continuar com a aposta (não bloquear)
                        else:
                            # Tempo positivo = jogo já começou, verificar se está na janela permitida
                            min_minute = self.soccer_config['entry_min_minute']
                            max_minute = self.soccer_config['entry_max_minute']
                            
                            if match_time < min_minute:
                                logger.info(f"⏱️ Mercado {market_id}: Jogo muito cedo ({match_time} min < {min_minute} min) - aguardando janela de entrada")
                                return None
                            
                            if match_time > max_minute:
                                logger.info(f"⏱️ Mercado {market_id}: Jogo muito avançado ({match_time} min > {max_minute} min) - janela de entrada passou - BLOQUEANDO aposta")
                                return None
                            
                            logger.info(f"⏱️ Mercado {market_id}: Tempo de jogo OK ({match_time} min) - dentro da janela [{min_minute}-{max_minute} min] - PERMITINDO aposta (fallback)")
                    else:
                        # Fallback ao vivo mas check_time_window desativado - não permitir
                        logger.info(f"⏱️ Mercado {market_id}: Fallback AO VIVO mas verificação de tempo desativada - BLOQUEANDO aposta")
                        return None
            elif check_time_window:
                # Estratégia ao vivo: verificar janela de tempo
                match_time = self.get_match_time(market_id)
                if match_time is None:
                    # Se não conseguir obter o tempo, assumir que o jogo ainda não começou
                    # (pode ser agendado para o futuro) e PERMITIR aposta
                    logger.info(f"⏱️ Mercado {market_id}: Não foi possível obter tempo de jogo - assumindo que jogo ainda não começou (agendado) - PERMITINDO aposta")
                    # Continuar com a aposta (não bloquear)
                elif match_time < 0:
                    # Tempo negativo = jogo ainda não começou (agendado para o futuro)
                    logger.info(f"⏱️ Mercado {market_id}: Jogo ainda não começou (tempo negativo: {match_time:.1f} min) - PERMITINDO aposta")
                    # Continuar com a aposta (não bloquear)
                else:
                    # Tempo positivo = jogo já começou, verificar se está na janela permitida
                    min_minute = self.soccer_config['entry_min_minute']
                    max_minute = self.soccer_config['entry_max_minute']
                    
                    if match_time < min_minute:
                        logger.info(f"⏱️ Mercado {market_id}: Jogo muito cedo ({match_time} min < {min_minute} min) - aguardando janela de entrada")
                        return None
                    
                    if match_time > max_minute:
                        logger.info(f"⏱️ Mercado {market_id}: Jogo muito avançado ({match_time} min > {max_minute} min) - janela de entrada passou - BLOQUEANDO aposta")
                        return None
                    
                    logger.info(f"⏱️ Mercado {market_id}: Tempo de jogo OK ({match_time} min) - dentro da janela [{min_minute}-{max_minute} min] - PERMITINDO aposta")
            else:
                logger.debug(f"Mercado {market_id}: Verificação de tempo de jogo desabilitada - pulando verificação")
            
            # Nova estratégia (sem Under 1.5):
            # permitir entrada quando o jogo ainda não passou de 1 gol total (0-0, 0-1 ou 1-0).
            # Se o IPS não fornecer placar, bloqueamos para não apostar com placar desconhecido.
            match_score = self.get_match_score(market_id)
            if not match_score:
                logger.warning(f"⚽ Mercado {market_id}: placar indisponível (IPS) — bloqueando entrada")
                return None

            home_score = match_score.get('home', 0)
            away_score = match_score.get('away', 0)
            try:
                h, a = int(home_score), int(away_score)
            except (ValueError, TypeError):
                logger.debug(f"Mercado {market_id}: placar inválido para conversão: {home_score}-{away_score}")
                return None

            total_so_far = h + a
            if total_so_far > 1:
                logger.info(
                    f"⚽ Mercado {market_id}: Placar {h}-{a} (total {total_so_far}) — Over {goal_line:.1f} sem hedge, pulando"
                )
                return None

            logger.info(f"⚽ Mercado {market_id}: Placar {h}-{a} (total {total_so_far}) — OK para Over {goal_line:.1f}")
            
            selection_id = over_runner.get('id') or over_runner.get('selectionId')
            if not selection_id:
                logger.warning(f"Mercado {market_id}: Runner Over {goal_line:.1f} sem ID válido")
                return None
            
            time_info = f" (Tempo: {match_time} min)" if match_time is not None else ""
            logger.info(f"✓ Condições Over {goal_line:.1f} atendidas para mercado {market_id}: Price {current_price}, Selection ID: {selection_id}{time_info}")
            return {
                'runner': over_runner,
                'price': current_price,
                'selection_id': selection_id,
                'match_time': match_time,
            }
        except Exception as e:
            logger.error(f"Erro ao verificar condições de futebol para {market_id}: {e}", exc_info=True)
            return None
    
    def place_lay_bet(self, market_id: str, selection_id: str, price: float, 
                     stake: float) -> Optional[str]:
        """Faz uma aposta LAY"""
        try:
            # Validar parâmetros
            if not market_id or not selection_id or price <= 1.0 or stake <= 0:
                logger.warning(f"Parâmetros inválidos para aposta LAY: market_id={market_id}, selection_id={selection_id}, price={price}, stake={stake}")
                return None
            
            # Calcular responsabilidade
            liability = stake * (price - 1)
            
            # Verificar saldo antes de fazer aposta
            balance = self.get_account_balance()
            if balance:
                if balance['available'] < liability:
                    logger.warning(f"Saldo insuficiente para aposta LAY. Disponível: R$ {balance['available']:.2f}, Necessário: R$ {liability:.2f}")
                    return None
            else:
                logger.warning("Não foi possível verificar saldo, mas continuando com a aposta LAY...")
            
            # Construir instrução - para Over/Under, handicap deve ser 0.0
            instruction = {
                'instructionType': 'PLACE',
                'handicap': 0.0,  # Obrigatório mesmo para Over/Under (deve ser 0.0)
                'side': 'LAY',
                'orderType': 'LIMIT',
                'limitOrder': {
                    'size': float(round(stake, 2)),  # Garantir que seja float
                    'price': float(round(price, 2)),  # Garantir que seja float
                    'persistenceType': 'LAPSE'  # Cancela se não for correspondida
                },
                'selectionId': int(selection_id)
            }
            
            instructions = [instruction]
            
            result = self.api.place_orders(
                market_id=str(market_id),  # Garantir que seja string
                instructions=instructions,
                customer_ref=f"bot_lay_{int(time.time())}"
            )
            
            if result and 'instructionReports' in result:
                report = result['instructionReports'][0]
                status = report.get('status')
                
                if status == 'SUCCESS':
                    bet_id = report.get('betId')
                    logger.info(f"✅✅✅ APOSTA LAY COLOCADA COM SUCESSO! Bet ID: {bet_id}, Price: {price:.2f}, Stake: {stake:.2f}")
                    return bet_id
                else:
                    error_code = report.get('errorCode', 'UNKNOWN')
                    error_message = report.get('sizeMatched', '')
                    instruction_error = report.get('instruction', {}).get('errorCode', '')
                    logger.error(f"❌ Falha ao colocar aposta LAY: Status={status}, ErrorCode={error_code}, InstructionError={instruction_error}, Message={error_message}")
                    if error_code == 'INSUFFICIENT_FUNDS':
                        balance = self.get_account_balance()
                        if balance:
                            logger.error(f"   Saldo disponível: R$ {balance['available']:.2f}, Necessário: R$ {liability:.2f}")
                    return None
            
            logger.warning(f"Resposta inválida ao colocar aposta LAY: {result}")
            return None
        except Exception as e:
            logger.error(f"Erro ao fazer aposta LAY: {e}", exc_info=True)
            return None
    
    def place_back_bet(self, market_id: str, selection_id: str, price: float, 
                      stake: float) -> Optional[str]:
        """Faz uma aposta BACK"""
        try:
            # Validar parâmetros básicos
            if not market_id:
                logger.error("place_back_bet: market_id é obrigatório")
                return None
            
            if not selection_id:
                logger.error("place_back_bet: selection_id é obrigatório")
                return None
            
            # Tentar converter selection_id para int
            try:
                selection_id_int = int(selection_id)
            except (ValueError, TypeError):
                logger.error(f"place_back_bet: selection_id inválido: {selection_id} (tipo: {type(selection_id)})")
                return None
            
            if price <= 1.0 or price > 1000:
                logger.error(f"place_back_bet: price inválido: {price}")
                return None
            
            if stake <= 0 or stake > 10000:
                logger.error(f"place_back_bet: stake inválido: {stake}")
                return None
            
            # Validar que price e stake são números válidos
            price_rounded = round(float(price), 2)
            stake_rounded = round(float(stake), 2)
            
            if price_rounded <= 1.0:
                logger.error(f"place_back_bet: price após arredondamento inválido: {price_rounded}")
                return None
            
            # Verificar saldo antes de fazer aposta BACK
            balance = self.get_account_balance()
            if balance:
                if balance['available'] < stake_rounded:
                    logger.warning(f"Saldo insuficiente para aposta BACK. Disponível: R$ {balance['available']:.2f}, Necessário: R$ {stake_rounded:.2f}")
                    return None
            else:
                logger.warning("Não foi possível verificar saldo, mas continuando com a aposta...")
            
            logger.debug(f"place_back_bet: market_id={market_id}, selection_id={selection_id_int}, price={price_rounded}, stake={stake_rounded}")
            
            # VALIDAÇÃO FINAL: Verificar se o mercado ainda está aberto e válido
            market_book_check = self.api.list_market_book(
                market_ids=[market_id],
                price_projection={'priceData': ['EX_BEST_OFFERS']}
            )
            
            if not market_book_check:
                logger.warning(f"place_back_bet: Não foi possível obter dados do mercado {market_id} antes da aposta")
                return None
            
            market_check = market_book_check[0]
            market_status = market_check.get('status')
            
            if market_status != 'OPEN':
                logger.warning(f"place_back_bet: Mercado {market_id} não está aberto (status: {market_status}) - abortando aposta")
                return None
            
            # Verificar se o runner ainda existe e tem liquidez
            runners_check = market_check.get('runners', [])
            runner_found = False
            current_price_valid = price_rounded
            
            for r in runners_check:
                r_id = r.get('id') or r.get('selectionId')
                if r_id == selection_id_int:
                    runner_found = True
                    available = r.get('ex', {}).get('availableToBack', [])
                    if not available or len(available) == 0:
                        logger.warning(f"place_back_bet: Runner {selection_id_int} sem liquidez para BACK")
                        return None
                    
                    # Usar o preço atual disponível
                    current_price_valid = round(available[0].get('price', 0), 2)
                    current_size = available[0].get('size', 0)
                    
                    if current_price_valid <= 1.0:
                        logger.warning(f"place_back_bet: Preço inválido: {current_price_valid}")
                        return None
                    
                    if current_size < stake_rounded:
                        min_stake = 2.0
                        if current_size >= min_stake:
                            logger.warning(
                                f"place_back_bet: Liquidez parcial {current_size:.2f} < {stake_rounded:.2f} "
                                f"— apostando o disponível: R${current_size:.2f}"
                            )
                            stake_rounded = round(current_size, 2)
                        else:
                            logger.warning(
                                f"place_back_bet: Liquidez insuficiente: {current_size:.2f} < stake mínimo {min_stake:.2f}"
                            )
                            return None
                    
                    # Se o preço mudou muito, usar o preço atual
                    if abs(current_price_valid - price_rounded) > 0.05:  # Tolerância de 5 centavos
                        logger.debug(f"place_back_bet: Preço mudou de {price_rounded} para {current_price_valid}, usando novo preço")
                        price_rounded = current_price_valid
                    break
            
            if not runner_found:
                logger.error(f"place_back_bet: Runner {selection_id_int} não encontrado no mercado {market_id}")
                logger.debug(f"Runners disponíveis: {[r.get('id') or r.get('selectionId') for r in runners_check]}")
                return None
            
            # Construir instrução - formato exato da API Betfair
            # IMPORTANTE: price deve ser um número (não string) e size também
            # Para Match Odds e alguns outros mercados, handicap NÃO deve ser enviado
            # Para mercados com handicap (Asian Handicap, etc), o handicap deve ser enviado
            
            # Para Match Odds (tênis, futebol, etc), NUNCA enviar handicap
            # Handicap só é necessário para mercados específicos como Asian Handicap
            # Vamos verificar o tipo de mercado pelo marketId ou pelo nome
            # Por segurança, para Match Odds, nunca enviar handicap
            
            # Construir instrução base - SEM handicap para Match Odds
            instruction = {
                'instructionType': 'PLACE',
                'side': 'BACK',
                'orderType': 'LIMIT',
                'limitOrder': {
                    'size': float(round(stake_rounded, 2)),  # Garantir que seja float
                    'price': float(round(price_rounded, 2)),  # Garantir que seja float
                    'persistenceType': 'LAPSE'
                },
                'selectionId': int(selection_id_int)
            }
            
            # IMPORTANTE: Para Match Odds, NÃO enviar handicap mesmo que o runner tenha um valor
            # O campo handicap só deve ser enviado para mercados específicos como:
            # - Asian Handicap
            # - Handicap markets
            # - Spread markets
            # 
            # Match Odds NÃO precisa de handicap, mesmo que o campo exista no runner
            logger.debug(f"place_back_bet: Match Odds - não enviando handicap (campo omitido)")
            
            instructions = [instruction]
            
            # Log detalhado antes de fazer a requisição
            logger.info(f"📤 Enviando aposta BACK: market_id={market_id}, selectionId={selection_id_int}, price={price_rounded}, size={stake_rounded}")
            logger.debug(f"📤 Instrução completa: {json.dumps(instruction, indent=2)}")
            
            try:
                # Garantir que market_id seja string
                result = self.api.place_orders(
                    market_id=str(market_id),
                    instructions=instructions,
                    customer_ref=f"bot_back_{int(time.time())}"
                )
                
                # Log da resposta
                logger.debug(f"📥 Resposta da API: {json.dumps(result, indent=2) if result else 'None'}")
            except Exception as api_error:
                # Verificar se é um erro da API (DSC-0018, etc)
                error_str = str(api_error)
                if 'DSC-0018' in error_str:
                    logger.error(f"❌ Erro DSC-0018 ao fazer aposta BACK: {api_error}")
                    logger.error(f"   Este erro geralmente indica parâmetros inválidos na requisição")
                    logger.error(f"   Market ID: {market_id}")
                    logger.error(f"   Selection ID: {selection_id_int} (tipo: {type(selection_id_int)})")
                    logger.error(f"   Price: {price_rounded} (tipo: {type(price_rounded)})")
                    logger.error(f"   Stake: {stake_rounded} (tipo: {type(stake_rounded)})")
                    logger.error(f"   Instrução enviada: {json.dumps(instruction, indent=2, default=str)}")
                    logger.error(f"   Handicap incluído: {'handicap' in instruction}")
                    
                    # Verificar se price está no formato correto (deve ser múltiplo de 0.01 e >= 1.01)
                    if price_rounded < 1.01:
                        logger.error(f"   ⚠️ PROBLEMA: Price muito baixo: {price_rounded}")
                    if price_rounded > 1000:
                        logger.error(f"   ⚠️ PROBLEMA: Price muito alto: {price_rounded}")
                    
                    # Verificar se size está no formato correto
                    if stake_rounded <= 0:
                        logger.error(f"   ⚠️ PROBLEMA: Stake inválido: {stake_rounded}")
                    
                    # Verificar se selectionId é válido
                    if selection_id_int <= 0:
                        logger.error(f"   ⚠️ PROBLEMA: Selection ID inválido: {selection_id_int}")
                    
                    # Tentar obter mais detalhes do mercado
                    try:
                        mb = self.api.list_market_book([market_id], price_projection={'priceData': ['EX_BEST_OFFERS']})
                        if mb:
                            market_data = mb[0]
                            logger.error(f"   Status do mercado: {market_data.get('status')}")
                            logger.error(f"   Market ID no response: {market_data.get('marketId')}")
                            logger.error(f"   Runners disponíveis: {[{'id': r.get('id'), 'handicap': r.get('handicap')} for r in market_data.get('runners', [])]}")
                            
                            # Verificar se o runner existe
                            target_runner = None
                            for r in market_data.get('runners', []):
                                if (r.get('id') or r.get('selectionId')) == selection_id_int:
                                    target_runner = r
                                    break
                            
                            if target_runner:
                                logger.error(f"   Runner encontrado: ID={target_runner.get('id')}, Handicap={target_runner.get('handicap')}")
                            else:
                                logger.error(f"   ⚠️ Runner {selection_id_int} NÃO encontrado no mercado!")
                    except Exception as debug_error:
                        logger.error(f"   Erro ao obter detalhes do mercado: {debug_error}")
                else:
                    logger.error(f"❌ Exceção ao fazer aposta BACK: {api_error}", exc_info=True)
                return None
            
            logger.debug(f"📥 Resposta da API: {result}")
            
            # Verificar se a resposta contém erro
            if result and isinstance(result, dict):
                if 'error' in result:
                    error_code = result.get('error', {}).get('code', 'UNKNOWN')
                    error_message = result.get('error', {}).get('message', '')
                    logger.error(f"❌ Erro na resposta da API: Code={error_code}, Message={error_message}")
                    return None
            
            if result and 'instructionReports' in result:
                report = result['instructionReports'][0]
                status = report.get('status')
                
                if status == 'SUCCESS':
                    bet_id = report.get('betId')
                    logger.info(f"✅✅✅ APOSTA BACK COLOCADA COM SUCESSO! Bet ID: {bet_id}, Price: {price_rounded}, Stake: {stake_rounded}")
                    return bet_id
                else:
                    error_code = report.get('errorCode', 'UNKNOWN')
                    error_message = report.get('sizeMatched', '')
                    instruction_error = report.get('instruction', {}).get('errorCode', '')
                    logger.error(f"❌ Falha ao colocar aposta BACK: Status={status}, ErrorCode={error_code}, InstructionError={instruction_error}, Message={error_message}")
                    logger.error(f"   Detalhes do report: {report}")
                    return None
            
            logger.warning(f"Resposta inválida ao colocar aposta BACK: {result}")
            return None
        except Exception as e:
            # Verificar se o erro contém informações sobre DSC-0018
            error_str = str(e)
            if 'DSC-0018' in error_str or 'code' in error_str:
                logger.error(f"❌ Erro DSC-0018 ao fazer aposta BACK: {e}")
                logger.error(f"   Parâmetros usados: market_id={market_id}, selection_id={selection_id}, price={price}, stake={stake}")
                logger.error(f"   selection_id_int={selection_id_int if 'selection_id_int' in locals() else 'N/A'}")
                logger.error(f"   Este erro geralmente indica que um parâmetro obrigatório está faltando ou inválido.")
                logger.error(f"   Verifique: selectionId (deve ser int), price (deve ser float > 1.0), size (deve ser float > 0)")
                logger.error(f"   Para mercados sem handicap (Match Odds, Over/Under simples), o campo 'handicap' não deve ser enviado.")
            else:
                logger.error(f"Erro ao fazer aposta BACK: {e}", exc_info=True)
            return None
    
    def cancel_bet(self, market_id: str, bet_id: str) -> bool:
        """Cancela uma aposta (Cash Out)"""
        try:
            result = self.api.cancel_orders(
                market_id=market_id,
                bet_ids=[bet_id],
                customer_ref=f"bot_cancel_{int(time.time())}"
            )
            
            if result and 'instructionReports' in result:
                report = result['instructionReports'][0]
                if report.get('status') == 'SUCCESS':
                    logger.info(f"Aposta cancelada (Cash Out): Bet ID {bet_id}")
                    return True
            
            return False
        except Exception as e:
            logger.error(f"Erro ao cancelar aposta: {e}")
            return False
    
    def check_and_close_bet(self, bet: ActiveBet) -> bool:
        """Verifica se uma aposta deve ser fechada e fecha se necessário"""
        try:
            market_book = self.api.list_market_book(
                market_ids=[bet.market_id],
                price_projection={'priceData': ['EX_BEST_OFFERS']}
            )
            
            if not market_book:
                return False
            
            runners = market_book[0].get('runners', [])
            current_runner = next((r for r in runners if r.get('id') == bet.selection_id), None)
            
            if not current_runner:
                return False
            
            # Obter preço atual
            if bet.side == 'LAY':
                available_to_lay = current_runner.get('ex', {}).get('availableToLay', [])
                if available_to_lay:
                    current_price = available_to_lay[0].get('price', bet.entry_price)
                else:
                    current_price = bet.entry_price
            else:  # BACK
                available_to_back = current_runner.get('ex', {}).get('availableToBack', [])
                if available_to_back:
                    current_price = available_to_back[0].get('price', bet.entry_price)
                else:
                    current_price = bet.entry_price
            
            bet.current_price = current_price
            
            # Calcular P&L
            if bet.side == 'LAY':
                # LAY: lucro quando preço sobe, perda quando preço cai
                price_change_pct = ((bet.entry_price - current_price) / bet.entry_price) * 100
                if current_price > bet.entry_price:
                    # Preço subiu = lucro
                    profit_pct = ((current_price - bet.entry_price) / bet.entry_price) * 100
                else:
                    # Preço caiu = perda
                    profit_pct = -((bet.entry_price - current_price) / bet.entry_price) * 100
            else:  # BACK
                # BACK: lucro quando preço cai, perda quando preço sobe
                price_change_pct = ((current_price - bet.entry_price) / bet.entry_price) * 100
                if current_price < bet.entry_price:
                    # Preço caiu = lucro
                    profit_pct = ((bet.entry_price - current_price) / bet.entry_price) * 100
                else:
                    # Preço subiu = perda
                    profit_pct = -((current_price - bet.entry_price) / bet.entry_price) * 100
            
            bet.profit_loss = profit_pct
            
            # Verificar Take Profit
            if profit_pct >= bet.take_profit_pct:
                # Para trading pré-jogo, fazer LAY para fechar (green book)
                if bet.strategy == "Pre-Match Trading" and bet.side == "BACK":
                    if self.close_pre_match_bet_with_lay(bet):
                        return True
                else:
                    # Para outras estratégias, apenas cancelar
                    if self.cancel_bet(bet.market_id, bet.bet_id):
                        bet.status = BetStatus.CLOSED_PROFIT
                        bet.close_reason = f"Take Profit: {profit_pct:.2f}%"
                        self.stats['profit_bets'] += 1
                        self.stats['total_profit'] += (bet.stake * profit_pct / 100)
                        
                        # Atualizar no banco de dados
                        self.db.close_bet(
                            bet.bet_id,
                            'CLOSED_PROFIT',
                            profit_pct,
                            bet.close_reason,
                            current_price
                        )
                        
                        logger.info(f"✓ Take Profit: {bet.sport.value} - {profit_pct:.2f}%")
                        return True
            
            # Verificar Stop Loss
            if profit_pct <= -bet.stop_loss_pct:
                # Para trading pré-jogo, fazer LAY para fechar (green book mesmo com perda)
                if bet.strategy == "Pre-Match Trading" and bet.side == "BACK":
                    if self.close_pre_match_bet_with_lay(bet):
                        return True
                else:
                    # Para outras estratégias, apenas cancelar
                    if self.cancel_bet(bet.market_id, bet.bet_id):
                        bet.status = BetStatus.CLOSED_LOSS
                        bet.close_reason = f"Stop Loss: {profit_pct:.2f}%"
                        self.stats['loss_bets'] += 1
                        self.stats['total_profit'] += (bet.stake * profit_pct / 100)
                        
                        # Atualizar no banco de dados
                        self.db.close_bet(
                            bet.bet_id,
                            'CLOSED_LOSS',
                            profit_pct,
                            bet.close_reason,
                            current_price
                        )
                        
                        logger.warning(f"✗ Stop Loss: {bet.sport.value} - {profit_pct:.2f}%")
                        return True
            
            # Verificar Timeout (apenas para futebol e hóquei)
            if bet.sport in [SportType.SOCCER, SportType.ICE_HOCKEY]:
                timeout_minutes = self.soccer_config['timeout_minutes'] if bet.sport == SportType.SOCCER else self.hockey_config['timeout_minutes']
                elapsed = (datetime.now() - bet.entry_time).total_seconds() / 60
                if elapsed >= timeout_minutes and profit_pct > 0:
                    if self.cancel_bet(bet.market_id, bet.bet_id):
                        bet.status = BetStatus.CLOSED_PROFIT
                        bet.close_reason = f"Timeout: {profit_pct:.2f}%"
                        self.stats['profit_bets'] += 1
                        self.stats['total_profit'] += (bet.stake * profit_pct / 100)
                        
                        # Atualizar no banco de dados
                        self.db.close_bet(
                            bet.bet_id,
                            'CLOSED_PROFIT',
                            profit_pct,
                            bet.close_reason,
                            current_price
                        )
                        
                        logger.info(f"✓ Timeout Profit: {bet.sport.value} - {profit_pct:.2f}%")
                        return True
            
            return False
        except Exception as e:
            logger.error(f"Erro ao verificar aposta {bet.bet_id}: {e}")
            return False
    
    def has_hedge_for_event(self, event_id: str) -> bool:
        """Verifica se já existe uma aposta hedge Under 1.5 para este evento (hoje ou ativa)."""
        try:
            today_bets = self.db.get_today_bets()
            for b in today_bets:
                if str(b.get('event_id', '')) == str(event_id):
                    strat = (b.get('strategy') or '').lower()
                    if 'under' in strat and 'hedge' in strat and '2.5' not in strat and '25' not in strat:
                        return True
        except Exception as e:
            logger.debug(f"Erro ao verificar hedge no banco para evento {event_id}: {e}")
        for b in self.active_bets.values():
            if str(b.event_id) == str(event_id):
                strat = b.strategy.lower()
                if 'under' in strat and 'hedge' in strat and '2.5' not in strat and '25' not in strat:
                    return True
        return False

    def has_under25_hedge_for_event(self, event_id: str) -> bool:
        """Verifica se já existe ao menos uma aposta hedge Under 2.5 para este evento."""
        return self.count_under25_hedge_for_event(event_id) >= 1

    def count_under25_hedge_for_event(self, event_id: str) -> int:
        """Conta quantas apostas hedge Under 2.5 já existem para este evento."""
        seen_ids = set()
        try:
            today_bets = self.db.get_today_bets()
            for b in today_bets:
                if str(b.get('event_id', '')) == str(event_id):
                    strat = (b.get('strategy') or '').lower()
                    if 'under' in strat and ('2.5' in strat or '25' in strat) and 'hedge' in strat:
                        bid = b.get('bet_id', '')
                        if bid:
                            seen_ids.add(str(bid))
        except Exception as e:
            logger.debug(f"Erro ao contar hedge 2.5 no banco para evento {event_id}: {e}")
        for b in self.active_bets.values():
            if str(b.event_id) == str(event_id):
                strat = b.strategy.lower()
                if 'under' in strat and ('2.5' in strat or '25' in strat) and 'hedge' in strat:
                    seen_ids.add(str(b.bet_id))
        return len(seen_ids)

    def count_high_hedges_for_event(self, event_id: str) -> int:
        """Conta quantas apostas Under Alta (4.5/5.5/6.5) já existem para este evento."""
        bet_ids = set()
        try:
            today_bets = self.db.get_today_bets()
            for b in today_bets:
                if str(b.get('event_id', '')) == str(event_id):
                    strat = (b.get('strategy') or '').lower()
                    if 'under' in strat and 'alta' in strat:
                        bet_id = str(b.get('bet_id', ''))
                        if bet_id:
                            bet_ids.add(bet_id)
        except Exception as e:
            logger.debug(f"Erro ao verificar under alta no banco para evento {event_id}: {e}")
        for b in self.active_bets.values():
            if str(b.event_id) == str(event_id):
                if 'under' in b.strategy.lower() and 'alta' in b.strategy.lower():
                    bet_ids.add(str(b.bet_id))
        return len(bet_ids)

    def _place_hedge_bet(self, event_id: str, event_name: str, hedge_market: Dict) -> bool:
        """Coloca a aposta hedge Under 1.5 e registra no banco. Retorna True se sucesso."""
        hedge_stake = self.soccer_config.get('under_hedge_stake', self.stake)
        hedge_bet_id = self.place_back_bet(
            market_id=hedge_market['market_id'],
            selection_id=hedge_market['selection_id'],
            price=hedge_market['price'],
            stake=hedge_stake,
        )
        if not hedge_bet_id:
            logger.warning(f"✗ Falha ao colocar hedge Under {hedge_market['goals_val']} para {event_name}")
            return False

        hedge_entry_time = datetime.now()
        hedge_strategy_name = f"Back Under {hedge_market['goals_val']} Hedge"
        hedge_bet = ActiveBet(
            bet_id=hedge_bet_id,
            market_id=hedge_market['market_id'],
            event_id=event_id,
            sport=SportType.SOCCER,
            strategy=hedge_strategy_name,
            side="BACK",
            selection_id=str(hedge_market['selection_id']),
            entry_price=hedge_market['price'],
            entry_time=hedge_entry_time,
            stake=hedge_stake,
            liability=0.0,
            take_profit_pct=self.soccer_config['take_profit_pct'],
            stop_loss_pct=self.soccer_config['stop_loss_pct'],
        )
        self.active_bets[hedge_bet_id] = hedge_bet
        self.stats['total_bets'] += 1
        self.stats['soccer_bets'] += 1
        self.db.insert_bet({
            'bet_id': hedge_bet_id,
            'market_id': hedge_market['market_id'],
            'event_id': event_id,
            'event_name': event_name,
            'sport': SportType.SOCCER.name,
            'strategy': hedge_strategy_name,
            'side': "BACK",
            'selection_id': str(hedge_market['selection_id']),
            'entry_price': hedge_market['price'],
            'entry_time': hedge_entry_time.isoformat(),
            'stake': hedge_stake,
            'liability': 0.0,
            'take_profit_pct': self.soccer_config['take_profit_pct'],
            'stop_loss_pct': self.soccer_config['stop_loss_pct'],
            'status': 'ACTIVE',
        })
        logger.info(f"✓✓✓ HEDGE COLOCADO: {hedge_market['market_name']} | {event_name} - Odd {hedge_market['price']:.2f} - Stake R$ {hedge_stake:.2f}")
        logger.info(f"   → GANHA se o jogo tiver MENOS de {hedge_market['goals_val']} gols")
        if self.telegram and self.telegram.enabled:
            try:
                balance = self.get_account_balance()
                self.telegram.notify_new_bet({
                    'bet_id': hedge_bet_id,
                    'event_name': event_name,
                    'sport': SportType.SOCCER.name,
                    'strategy': hedge_strategy_name,
                    'side': "BACK",
                    'entry_price': hedge_market['price'],
                    'stake': hedge_stake,
                    'liability': 0.0,
                }, balance)
            except Exception as e:
                logger.warning(f"Erro ao notificar Telegram (hedge): {e}")
        return True

    def _place_high_hedge_bet(self, event_id: str, event_name: str, high_market: Dict, strategy_name: Optional[str] = None) -> bool:
        """Coloca uma aposta Under Alta e registra no banco."""
        stake = self.soccer_config.get('under_high_hedge_stake', self.stake)
        bet_id = self.place_back_bet(
            market_id=high_market['market_id'],
            selection_id=high_market['selection_id'],
            price=high_market['price'],
            stake=stake,
        )
        if not bet_id:
            logger.warning(f"  ❌ Falha ao colocar Under Alta para {event_name}")
            return False

        strategy_name = strategy_name or f"Back Under {high_market['goals_val']} Alta"
        entry_time = datetime.now()
        self.active_bets[bet_id] = ActiveBet(
            bet_id=bet_id,
            market_id=high_market['market_id'],
            event_id=event_id,
            sport=SportType.SOCCER,
            strategy=strategy_name,
            side="BACK",
            selection_id=str(high_market['selection_id']),
            entry_price=high_market['price'],
            entry_time=entry_time,
            stake=stake,
            liability=0.0,
            take_profit_pct=self.soccer_config['take_profit_pct'],
            stop_loss_pct=self.soccer_config['stop_loss_pct'],
        )
        self.stats['total_bets'] += 1
        self.stats['soccer_bets'] += 1
        self.db.insert_bet({
            'bet_id': bet_id,
            'market_id': high_market['market_id'],
            'event_id': event_id,
            'event_name': event_name,
            'sport': SportType.SOCCER.name,
            'strategy': strategy_name,
            'side': 'BACK',
            'selection_id': str(high_market['selection_id']),
            'entry_price': high_market['price'],
            'entry_time': entry_time.isoformat(),
            'stake': stake,
            'liability': 0.0,
            'take_profit_pct': self.soccer_config['take_profit_pct'],
            'stop_loss_pct': self.soccer_config['stop_loss_pct'],
            'status': 'ACTIVE',
        })
        logger.info(f"  ✅ Under Alta executada! Bet ID {bet_id} — Under {high_market['goals_val']} @ {high_market['price']:.2f}")
        return True

    def process_under_hedge_monitoring(self):
        """
        Monitora jogos em que apostamos Over 0.5 hoje (últimas 3h) e coloca o hedge
        Under 1.5 quando a odd atingir o mínimo configurado.
        O monitoramento continua durante TODO o jogo, mesmo após o Over 0.5 já ter
        ganho — o filtro de 25 minutos é só para entrar no Over 0.5, não para o hedge.
        """
        # RETIRADO: a estratégia de hedge Under 1.5 será substituída por uma nova lógica.
        # Mantemos a função apenas por compatibilidade com chamadas antigas, mas não executa apostas.
        logger.info("🛑 Hedge Under 1.5 aposentado — nenhuma aposta será executada.")
        return

        try:
            # Buscar apostas de hoje (inclui ACTIVE, CLOSED_PROFIT, etc.)
            today_bets = self.db.get_today_bets()
        except Exception as e:
            logger.debug(f"Hedge monitor: erro ao ler banco: {e}")
            return

        # Janela de 3h: cobre um jogo inteiro de 90 min + alguma margem
        cutoff = datetime.now() - timedelta(hours=3)

        pending = []
        seen_events = set()
        for b in today_bets:
            strat = (b.get('strategy') or '').lower()

            # Precisa ser uma aposta "Back Over ..." original
            # (hoje a estratégia pode ser Back Over 1.5, então não pode filtrar só por 0.5)
            if 'back over' not in strat:
                continue
            # Excluir proteção 0-0 e hedges (não tratá-los como Over 0.5)
            if 'proteção' in strat or 'protecao' in strat or 'hedge' in strat:
                continue

            # Verificar se foi colocada nas últimas 3 horas
            try:
                entry_time_str = b.get('entry_time', '')
                if 'T' in entry_time_str:
                    entry_dt = datetime.fromisoformat(entry_time_str.replace('Z', ''))
                else:
                    entry_dt = datetime.strptime(entry_time_str, '%Y-%m-%d %H:%M:%S')
                if entry_dt < cutoff:
                    continue
            except Exception:
                continue

            eid = str(b.get('event_id', ''))
            if not eid or eid in seen_events:
                continue
            u25_c = self.count_under25_hedge_for_event(eid)
            u15_exists = self.has_hedge_for_event(eid)
            # Pula se já completou as 2 apostas (2x Under 2.5 OU fallback Under 1.5 já aplicado)
            if u25_c >= 2:
                continue
            if u25_c == 0 and u15_exists:
                continue
            seen_events.add(eid)
            pending.append(b)

        if not pending:
            return

        logger.info(f"🔍 Monitorando hedge: {len(pending)} jogo(s) aguardando Under 1.5 ≥ {self.soccer_config.get('min_odd', 2.15):.2f}")

        min_minute = self.soccer_config.get('under_hedge_min_minute', 73)
        for bet in pending:
            event_id = str(bet.get('event_id', ''))
            event_name = bet.get('event_name', event_id)
            market_id = bet.get('market_id', '')

            # Verificar minuto mínimo de jogo antes de colocar Under 1.5
            if market_id and min_minute > 0:
                game_minute = self.get_live_match_minute(market_id)
                if game_minute is None:
                    logger.debug(f"  ⏳ {event_name}: não foi possível calcular minuto do jogo — aguardando")
                    continue
                if game_minute < min_minute:
                    logger.debug(f"  ⏳ {event_name}: minuto {game_minute} < {min_minute} — aguardando Under 1.5")
                    continue
                logger.info(f"  ⏱️ {event_name}: minuto {game_minute} ≥ {min_minute} — verificando Under 1.5")

            score = self.get_match_score(market_id) if market_id else None
            if not score:
                # Feed de placar indisponível: sem score não dá para garantir que ainda está 0-0.
                # Melhor não hedgear do que hedgear com inferência errada.
                logger.debug(f"  ⏳ {event_name}: placar indisponível (IPS) — aguardando para hedge")
                continue
            if score.get('total') != 0:
                logger.info(
                    f"  🚫 {event_name}: placar atual {score.get('home')}-{score.get('away')} — "
                    "Under 2.5/1.5 cancelado, só entra com 0-0 confirmado"
                )
                continue

            # ── LÓGICA: coloca 2 apostas juntas de uma vez ──
            # Prioridade: 2x Under 2.5 | Fallback: 2x Under 1.5
            hedge_stake = self.soccer_config.get('under_hedge_stake', self.stake)
            u25_count = self.count_under25_hedge_for_event(event_id)
            u15_count = 1 if self.has_hedge_for_event(event_id) else 0

            # Já colocou as 2 apostas → pula
            if u25_count >= 2 or (u25_count == 0 and u15_count >= 2):
                continue

            under25_market = self.find_under_25_market(event_id)

            if under25_market:
                # Under 2.5 disponível → coloca 2x de uma vez
                entries_needed = 2 - u25_count
                logger.info(
                    f"  ✅ Under 2.5 disponível @ {under25_market['price']:.2f} → "
                    f"colocando {entries_needed}x aposta(s) em {event_name}"
                )
                for entry_num in range(u25_count + 1, u25_count + entries_needed + 1):
                    u25_bet_id = self.place_back_bet(
                        market_id=under25_market['market_id'],
                        selection_id=under25_market['selection_id'],
                        price=under25_market['price'],
                        stake=hedge_stake,
                    )
                    if u25_bet_id:
                        self.db.insert_bet({
                            'bet_id': u25_bet_id,
                            'market_id': under25_market['market_id'],
                            'event_id': event_id,
                            'event_name': event_name,
                            'sport': 'SOCCER',
                            'strategy': 'Back Under 2.5 Hedge',
                            'side': 'BACK',
                            'selection_id': str(under25_market['selection_id']),
                            'entry_price': under25_market['price'],
                            'entry_time': datetime.now().isoformat(),
                            'stake': hedge_stake,
                            'liability': 0.0,
                            'take_profit_pct': 0.0,
                            'stop_loss_pct': 0.0,
                            'status': 'ACTIVE',
                        })
                        logger.info(
                            f"    ✅ Under 2.5 #{entry_num}/2 colocado! Bet ID {u25_bet_id} "
                            f"@ {under25_market['price']:.2f}"
                        )
                        if self.telegram and self.telegram.enabled:
                            try:
                                self.telegram.send_message(
                                    f"🛡️ UNDER 2.5 HEDGE #{entry_num}/2\n"
                                    f"Jogo: {event_name}\n"
                                    f"BACK Under 2.5 @ {under25_market['price']:.2f} | Stake R${hedge_stake:.2f}\n"
                                    f"Bet ID: {u25_bet_id}"
                                )
                            except Exception:
                                pass
                    else:
                        logger.debug(f"    ⏳ {event_name}: falha ao colocar Under 2.5 #{entry_num}")
            else:
                # Under 2.5 indisponível → fallback: 2x Under 1.5
                hedge_market = self.find_best_under_market(event_id) if u15_count == 0 else None
                if hedge_market:
                    logger.info(
                        f"  ⚠️ Under 2.5 indisponível → fallback 2x Under 1.5 "
                        f"@ {hedge_market['price']:.2f} em {event_name}"
                    )
                    for entry_num in range(1, 3):
                        self._place_hedge_bet(event_id, event_name, hedge_market)
                        logger.info(f"    ✅ Under 1.5 #{entry_num}/2 colocado @ {hedge_market['price']:.2f}")
                else:
                    logger.debug(
                        f"  ⏳ {event_name}: Under 2.5 e Under 1.5 indisponíveis "
                        f"(Under 2.5 odd mínima ≥ {self.soccer_config.get('under_25_min_odd', 1.35):.2f}, "
                        f"Under 1.5 odd mínima ≥ {self.soccer_config.get('min_odd', 2.15):.2f})"
                    )

    def process_under_high_hedge_monitoring(self):
        """
        3ª aposta da estratégia: BACK Under 4.5/5.5/6.5 como proteção intermediária.
        Pode entrar em quase todo o jogo, inclusive no 0-0 para somar lucro com o Under 1.5.
        Permitimos até 2 entradas por evento:
          1. primeira entrada como proteção ampla;
          2. segunda entrada recorrente igual à primeira, no mesmo jogo.
        """
        if not self.soccer_config.get('under_high_hedge_enabled', False):
            return

        try:
            today_bets = self.db.get_today_bets()
        except Exception as e:
            logger.debug(f"Under Alta monitor: erro ao ler banco: {e}")
            return

        cutoff = datetime.now() - timedelta(hours=3)
        trigger_minute = self.soccer_config.get('under_high_hedge_trigger_minute', 40)
        end_minute = self.soccer_config.get('under_high_hedge_end_minute', 88)
        max_entries = max(1, self.soccer_config.get('under_high_hedge_max_entries', 2))

        pending = []
        seen_events: set = set()
        for b in today_bets:
            strat = (b.get('strategy') or '').lower()
            if 'over 0.5' not in strat and 'over_05' not in strat:
                continue
            if 'proteção' in strat or 'protecao' in strat or 'hedge' in strat or 'alta' in strat:
                continue
            try:
                entry_time_str = b.get('entry_time', '')
                if 'T' in entry_time_str:
                    entry_dt = datetime.fromisoformat(entry_time_str.replace('Z', ''))
                else:
                    entry_dt = datetime.strptime(entry_time_str, '%Y-%m-%d %H:%M:%S')
                if entry_dt < cutoff:
                    continue
            except Exception:
                continue

            eid = str(b.get('event_id', ''))
            if not eid or eid in seen_events:
                continue
            seen_events.add(eid)
            pending.append(b)

        if not pending:
            return

        logger.info(
            f"🔍 Monitorando Under Alta: {len(pending)} jogo(s) candidatos "
            f"(janela {trigger_minute}-{end_minute} min, máx {max_entries} entradas)"
        )

        second_entry_minute = self.soccer_config.get('under_high_hedge_second_entry_minute', 60)
        for bet in pending:
            event_id = str(bet.get('event_id', ''))
            event_name = bet.get('event_name', event_id)
            market_id = bet.get('market_id', '')

            if not market_id:
                continue

            score = self.get_match_score(market_id)
            game_minute = self.get_live_match_minute(market_id, score)

            high_hedge_count = self.count_high_hedges_for_event(event_id)
            if high_hedge_count >= max_entries:
                logger.debug(f"  ⏳ {event_name}: já possui {high_hedge_count} Under Alta — limite atingido")
                continue

            if score:
                total_goals = score.get('total', 0)
                score_label = f"{score.get('home')}-{score.get('away')}"
            else:
                total_goals = None
                score_label = "desconhecido"

            # 1ª entrada: pode apostar imediatamente (pré-jogo ou ao vivo), sem exigir minuto
            # 2ª entrada: exige minuto e só após second_entry_minute
            if high_hedge_count >= 1:
                if game_minute is None:
                    logger.debug(f"  ⏳ {event_name}: 2ª Under Alta — minuto desconhecido, aguardando")
                    continue
                if game_minute < second_entry_minute:
                    logger.debug(
                        f"  ⏳ {event_name}: 2ª Under Alta só após minuto {second_entry_minute} "
                        f"(agora {game_minute})"
                    )
                    continue

            # Para 1ª entrada: sem filtro de minuto (pode ser pré-jogo)

            entry_number = high_hedge_count + 1
            min_odd_first = self.soccer_config.get('under_high_hedge_min_odd_first_entry', 1.08)
            min_odd_normal = self.soccer_config.get('under_high_hedge_min_odd', 1.15)
            min_odd_used = min_odd_first if high_hedge_count == 0 else min_odd_normal
            min_info = f"minuto {game_minute}" if game_minute is not None else "pré-jogo"
            logger.info(
                f"  ⏱️ {event_name}: {min_info} | placar {score_label} | "
                f"buscando Under Alta #{entry_number} (odd mín {min_odd_used:.2f})"
            )
            high_market = self.find_under_high_market(event_id, min_odd_override=min_odd_used)
            if not high_market:
                logger.debug(f"  ⏳ {event_name}: nenhum Under Alta disponível com odd ≥ {min_odd_used:.2f}")
                continue

            stake = self.soccer_config.get('under_high_hedge_stake', self.stake)
            price = high_market['price']
            goals_val = high_market['goals_val']

            if total_goals is not None and goals_val <= total_goals:
                logger.debug(
                    f"  🚫 {event_name}: mercado Under {goals_val} inválido para placar {score_label}"
                )
                continue

            min_display = game_minute if game_minute is not None else "pré"
            logger.info(
                f"  🛡️ UNDER ALTA: {event_name} | Under {goals_val} @ {price:.2f} | "
                f"Stake R${stake:.2f} | Minuto {min_display} | Entrada #{entry_number}"
            )
            self._place_high_hedge_bet(
                event_id=event_id,
                event_name=event_name,
                high_market=high_market,
                strategy_name=f"Back Under {goals_val} Alta",
            )

    def _find_cs_zero_zero(self, event_id: str, min_odd: float = 1.01) -> Optional[Dict]:
        """
        Busca o mercado de Placar Exato 0-0 para o evento.
        Retorna dict com market_id, selection_id, price, available_size ou None.
        """
        try:
            markets = self.api.list_market_catalogue(
                filter_dict={
                    'eventTypeIds': ['1'],
                    'marketTypeCodes': ['CORRECT_SCORE'],
                    'eventIds': [str(event_id)],
                },
                market_projection=['MARKET_DESCRIPTION', 'RUNNER_DESCRIPTION', 'EVENT'],
                max_results=5
            ) or []

            if not markets:
                logger.debug(f"CS 0-0: nenhum mercado CORRECT_SCORE para evento {event_id}")
                return None

            cs_market = markets[0]
            cs_market_id = cs_market.get('marketId')
            runners_cat = cs_market.get('runners', [])

            zero_zero_runner = None
            for r in runners_cat:
                name = (r.get('runnerName') or '').strip().lower().replace(' ', '')
                if name in ('0-0', '00', 'nilnil', '0–0'):
                    zero_zero_runner = r
                    break

            if not zero_zero_runner:
                logger.debug(f"CS 0-0: runner '0-0' não encontrado em {cs_market_id} (runners: {[r.get('runnerName') for r in runners_cat[:6]]})")
                return None

            selection_id = str(zero_zero_runner.get('selectionId', ''))

            books = self.api.list_market_book(
                market_ids=[cs_market_id],
                price_projection={'priceData': ['EX_BEST_OFFERS']}
            ) or []

            if not books:
                return None

            for br in books[0].get('runners', []):
                rid = str(br.get('id') or br.get('selectionId', ''))
                if rid == selection_id:
                    available_to_back = br.get('ex', {}).get('availableToBack', [])
                    if not available_to_back:
                        logger.debug(f"CS 0-0: sem liquidez para 0-0 em {cs_market_id}")
                        return None
                    price = available_to_back[0].get('price', 0)
                    size = available_to_back[0].get('size', 0)
                    if price <= 1.0 or price < min_odd:
                        logger.debug(f"CS 0-0: odd {price:.2f} < mínima {min_odd:.2f} — ignorando")
                        return None
                    return {
                        'market_id': cs_market_id,
                        'selection_id': selection_id,
                        'price': price,
                        'available_size': size,
                        'type': 'CS_00',
                    }
        except Exception as e:
            logger.debug(f"CS 0-0: erro ao buscar mercado: {e}")
        return None

    def _find_under05_runner(self, market_id: str, over05_selection_id: str, books_cache: Optional[list] = None) -> Optional[Dict]:
        """
        Encontra o runner Under 0.5 no mesmo mercado Over/Under 0.5.
        É o segundo runner (diferente do Over 0.5 já apostado).
        """
        try:
            books = books_cache or (self.api.list_market_book(
                market_ids=[market_id],
                price_projection={'priceData': ['EX_BEST_OFFERS']}
            ) or [])

            if not books:
                return None

            runners = books[0].get('runners', [])
            for r in runners:
                rid = str(r.get('id') or r.get('selectionId', ''))
                if rid != str(over05_selection_id):
                    available_to_back = r.get('ex', {}).get('availableToBack', [])
                    if not available_to_back:
                        return None
                    price = available_to_back[0].get('price', 0)
                    size = available_to_back[0].get('size', 0)
                    if price <= 1.0:
                        return None
                    return {
                        'market_id': market_id,
                        'selection_id': rid,
                        'price': price,
                        'available_size': size,
                        'type': 'UNDER_05',
                    }
        except Exception as e:
            logger.debug(f"Under 0.5 fallback: erro ao buscar: {e}")
        return None

    def process_zero_zero_protection(self):
        """
        Proteção Under 1.5: quando a odd do Over 0.5 chega no threshold configurado,
        busca BACK Under 1.5 com odd mínima configurada para:
          1. Cobrir o cenário de 0-0
          2. Ganhar junto com o Over 0.5 quando sair exatamente 1 gol
        Stake = original_stake / (protection_price - 1) para cobrir exatamente o 0-0.
        Proteção aplicada apenas UMA vez por evento (4 camadas anti-loop).
        """
        if not self.soccer_config.get('stop_loss_lay_enabled', False):
            return

        threshold = self.soccer_config.get('stop_loss_lay_threshold', 2.0)

        try:
            db_bets = self.db.get_active_bets()
        except Exception as e:
            logger.debug(f"Proteção Under 1.5: erro ao ler banco: {e}")
            return

        # Camada 4: event_ids com proteção já registrada no banco (sobrevive reinicios)
        events_with_protection: set = set()
        for b in db_bets:
            strat = (b.get('strategy') or '').lower()
            if (
                ('proteção' in strat or 'protecao' in strat)
                or ('hedge' in strat and 'under' in strat)
                or ('0-0' in strat)
                or ('partial stop-loss' in strat or 'lay over 0.5' in strat)
            ):
                eid = str(b.get('event_id', ''))
                if eid:
                    events_with_protection.add(eid)

        pending = []
        for b in db_bets:
            strat = (b.get('strategy') or '').lower()
            side = (b.get('side') or '').upper()
            status = (b.get('status') or '').upper()
            # Camada 1: só BACK ativas
            if status != 'ACTIVE' or side != 'BACK':
                continue
            # Camada 2: estratégia exatamente "back over 0.5"
            if strat != 'back over 0.5':
                continue
            bet_id = str(b.get('bet_id', ''))
            if not bet_id:
                continue
            # Camada 3: não aplicar duas vezes (memória runtime)
            if bet_id in self._stop_loss_applied:
                continue
            # Camada 4: verificar banco
            eid = str(b.get('event_id', ''))
            if eid in events_with_protection:
                continue
            pending.append(b)

        if not pending:
            return

        # Agrupar por market_id para reduzir chamadas de API
        markets_to_check: Dict[str, list] = {}
        for b in pending:
            mid = b.get('market_id', '')
            if mid:
                markets_to_check.setdefault(mid, []).append(b)

        for market_id, bets in markets_to_check.items():
            try:
                market_books = self.api.list_market_book(
                    market_ids=[market_id],
                    price_projection={'priceData': ['EX_BEST_OFFERS']}
                )
                if not market_books:
                    continue

                runners = market_books[0].get('runners', [])

                for bet in bets:
                    bet_id = str(bet.get('bet_id', ''))
                    selection_id = str(bet.get('selection_id', ''))
                    original_stake = float(bet.get('stake', self.stake))
                    event_name = bet.get('event_name', bet_id)
                    event_id = str(bet.get('event_id', ''))

                    # Verificar odd atual do Over 0.5
                    target_runner = None
                    for r in runners:
                        rid = str(r.get('id') or r.get('selectionId', ''))
                        if rid == selection_id:
                            target_runner = r
                            break

                    if not target_runner:
                        continue

                    available_to_back = target_runner.get('ex', {}).get('availableToBack', [])
                    if not available_to_back:
                        continue

                    current_over05_price = available_to_back[0].get('price', 0)
                    score = self.get_match_score(market_id)

                    if current_over05_price < threshold:
                        logger.debug(f"Proteção: {event_name} odd Over 0.5 {current_over05_price:.2f} < {threshold:.2f}, aguardando...")
                        continue

                    logger.info(
                        f"🛡️ PROTEÇÃO UNDER 1.5 ATIVADA: {event_name} | "
                        f"Over 0.5 odd atual {current_over05_price:.2f} ≥ threshold {threshold:.2f}"
                    )
                    # Quando feed de placar indisponível, inferir 0-0 pela odd:
                    # odd alta (≥ threshold) já prova que o jogo está 0-0
                    if not score:
                        inferred_zero = current_over05_price >= threshold
                        if inferred_zero:
                            logger.info(
                                f"   ⚠️ {event_name}: placar indisponível, mas odd Over 0.5 "
                                f"{current_over05_price:.2f} ≥ {threshold:.2f} → inferindo 0-0"
                            )
                            score = {'home': 0, 'away': 0, 'total': 0, 'status': ''}
                        else:
                            logger.warning(f"   ❌ Placar indisponível para {event_name} — proteção depende do score atual")
                            continue

                    total_goals = score.get('total', 0)
                    score_label = f"{score.get('home')}-{score.get('away')}"
                    game_minute = self.get_live_match_minute(market_id, score)
                    score_status = score.get('status', '')
                    score_status_minute = self._extract_score_status_minute(score_status)

                    protection = None
                    label = ''
                    strategy_name = ''
                    protection_mode = 'coverage'

                    if total_goals == 0:
                        min_under_minute = self.soccer_config.get('under_hedge_min_minute', 73)
                        min_cs_late = self.soccer_config.get('cs00_fallback_min_minute', 88)
                        cs_min_odd = 2.10
                        time_available = game_minute is not None
                        second_half = self._is_second_half(game_minute, score_status)

                        if not time_available:
                            logger.warning(
                                f"   ⏱️ {event_name}: tempo indisponível, score 0-0 — usando odd do CS como gatilho principal"
                            )

                        # ── PRIORIDADE 1: 0-0 CS no 2º tempo com odd >= 2.10
                        if (second_half or not time_available) and event_id:
                            protection = self._find_cs_zero_zero(event_id, min_odd=cs_min_odd)
                            if protection:
                                label = '0-0 Correct Score'
                                strategy_name = 'Proteção 0-0'
                                protection_mode = 'fixed'
                                logger.info(
                                    f"   ✅ {event_name}: 0-0 CS @ {protection['price']:.2f} ≥ {cs_min_odd:.2f} "
                                    f"no 2º tempo → BACK fixo de R$15"
                                )

                        # ── PRIORIDADE 2: Under 2.5 (min 65 real = 73)
                        if not protection:
                            if time_available and game_minute < min_under_minute:
                                logger.warning(
                                    f"   ❌ {event_name}: ainda cedo para proteção (min {game_minute} < {min_under_minute}) "
                                    f"e 0-0 CS < {cs_min_odd:.2f}"
                                )
                                continue
                            protection = self.find_under_25_market(event_id, min_odd_override=1.05) if event_id else None
                            if protection:
                                label = 'Under 2.5'
                                strategy_name = 'Proteção Under 2.5'
                                protection_mode = 'fixed'

                        # PRIORIDADE 3 removida: hedge/proteção Under 1.5 aposentado

                        # ── PRIORIDADE 4: 0-0 CS tardio como último recurso
                        if not protection:
                            if time_available and game_minute >= min_cs_late and event_id:
                                protection = self._find_cs_zero_zero(event_id)
                                if protection:
                                    label = '0-0 Correct Score'
                                    strategy_name = 'Proteção 0-0'
                                    protection_mode = 'fixed'
                                    logger.info(
                                        f"   ⚠️ {event_name}: fallback tardio 0-0 CS @ {protection['price']:.2f} "
                                        f"no min {game_minute} — BACK fixo de R$15"
                                    )

                        if not protection:
                            logger.warning(
                                f"   ❌ Nenhuma proteção disponível para {event_name}: "
                                f"CS 0-0 < {cs_min_odd:.2f}, Under 2.5/1.5 indisponíveis "
                                f"e fallback tardio não disponível (minuto {game_minute})"
                            )
                            continue
                    else:
                        protection = self.find_under_25_market(event_id) if event_id else None
                        label = 'Under 2.5'
                        strategy_name = 'Proteção Under 2.5'
                        protection_mode = 'fixed'
                        if not protection:
                            logger.warning(
                                f"   ❌ Nenhuma proteção Under 2.5 disponível para {event_name} "
                                f"com odd mínima {self.soccer_config.get('under_25_min_odd', 1.35):.2f}"
                            )
                            continue

                    # Sem prioridade Under 1.5 (aposentado)

                    prot_price = protection['price']
                    over05_entry_price = float(bet.get('entry_price', 1.0) or 1.0)
                    over05_profit_if_goal = round(original_stake * max(0.0, over05_entry_price - 1.0), 2)

                    if protection_mode == 'coverage':
                        prot_stake = round(original_stake / max(0.01, (prot_price - 1)), 2)
                        prot_stake = min(prot_stake, original_stake * 3)
                        prot_stake = max(prot_stake, 2.0)
                        net_if_nil_nil = round((prot_stake * (prot_price - 1)) - original_stake, 2)
                        net_if_one_goal = round(over05_profit_if_goal + (prot_stake * (prot_price - 1)), 2)
                        net_if_two_plus = round(over05_profit_if_goal - prot_stake, 2)
                        logger.info(
                            f"   BACK {label}: stake R${prot_stake:.2f} @ {prot_price:.2f} | "
                            f"Placar {score_label} | 0-0: R${net_if_nil_nil:.2f} | "
                            f"1 gol: R${net_if_one_goal:.2f} | 2+ gols: R${net_if_two_plus:.2f}"
                        )
                    else:
                        prot_stake = self.soccer_config.get('under_hedge_stake', self.stake)
                        logger.info(
                            f"   BACK {label}: stake fixa R${prot_stake:.2f} @ {prot_price:.2f} | "
                            f"Placar atual {score_label} | proteção após gol"
                        )

                    prot_bet_id = self.place_back_bet(
                        market_id=protection['market_id'],
                        selection_id=protection['selection_id'],
                        price=prot_price,
                        stake=prot_stake
                    )

                    if prot_bet_id:
                        self._stop_loss_applied.add(bet_id)
                        logger.info(f"✅ {strategy_name} executada! Bet ID {prot_bet_id} ({label} @ {prot_price:.2f})")

                        self.db.insert_bet({
                            'bet_id': prot_bet_id,
                            'market_id': protection['market_id'],
                            'event_id': event_id,
                            'event_name': event_name,
                            'sport': 'SOCCER',
                            'strategy': strategy_name,
                            'side': 'BACK',
                            'selection_id': protection['selection_id'],
                            'entry_price': prot_price,
                            'entry_time': datetime.now().isoformat(),
                            'stake': prot_stake,
                            'liability': 0.0,
                            'take_profit_pct': 0.0,
                            'stop_loss_pct': 0.0,
                            'status': 'ACTIVE',
                        })

                        if self.telegram and self.telegram.enabled:
                            try:
                                msg = (
                                    f"🛡️ {strategy_name.upper()}\n"
                                    f"Jogo: {event_name}\n"
                                    f"Placar atual: {score_label}\n"
                                    f"Over 0.5 odd subiu para {current_over05_price:.2f} (threshold {threshold:.2f})\n"
                                    f"BACK {label}: R${prot_stake:.2f} @ {prot_price:.2f}\n"
                                )
                                if protection_mode == 'coverage':
                                    msg += (
                                        f"0-0: R${net_if_nil_nil:.2f} | "
                                        f"1 gol: R${net_if_one_goal:.2f} | 2+ gols: R${net_if_two_plus:.2f}"
                                    )
                                else:
                                    msg += "Proteção após gol via Under 2.5"
                                self.telegram.send_message(msg)
                            except Exception as tg_err:
                                logger.debug(f"Erro Telegram proteção Under 1.5: {tg_err}")

                        if total_goals > 0 and event_id:
                            high_hedge_count = self.count_high_hedges_for_event(event_id)
                            max_entries = max(1, self.soccer_config.get('under_high_hedge_max_entries', 2))
                            if high_hedge_count < max_entries:
                                high_market = self.find_under_high_market(event_id)
                                if high_market:
                                    high_goals_val = high_market.get('goals_val', 0)
                                    if high_goals_val > total_goals:
                                        logger.info(
                                            f"   🔁 Reforço após gol: tentando Under Alta extra para {event_name} "
                                            f"(placar {score_label})"
                                        )
                                        self._place_high_hedge_bet(
                                            event_id=event_id,
                                            event_name=event_name,
                                            high_market=high_market,
                                            strategy_name=f"Back Under {high_goals_val} Alta Reforço",
                                        )
                                    else:
                                        logger.debug(
                                            f"   ⏳ Reforço Under Alta ignorado: Under {high_goals_val} inválido para placar {score_label}"
                                        )
                    else:
                        logger.warning(f"❌ Falha ao executar {strategy_name} para {event_name}")

            except Exception as e:
                logger.error(f"Erro na proteção Under 1.5 para mercado {market_id}: {e}", exc_info=True)

    def process_soccer_strategy(self):
        """Processa estratégia de futebol"""
        if not self.soccer_config['enabled']:
            logger.debug("Estratégia de futebol desabilitada")
            return
        
        # Verificar se está em modo pré-jogo
        pre_match_mode = self.soccer_config.get('pre_match_enabled', False)
        if pre_match_mode:
            logger.info("🎯 Buscando partidas de futebol PRÉ-JOGO (antes do jogo começar)...")
        else:
            logger.info("🔍 Buscando partidas de futebol ao vivo...")
        matches = self.find_live_soccer_matches()
        if pre_match_mode:
            logger.info(f"📊 Encontradas {len(matches)} partidas de futebol PRÉ-JOGO")
        else:
            logger.info(f"📊 Encontradas {len(matches)} partidas de futebol ao vivo")
        
        if len(matches) == 0:
            logger.debug("Nenhuma partida de futebol encontrada no momento")
        
        matches_checked = 0
        matches_with_conditions = 0
        
        # Verificar saldo antes de processar
        balance = self.get_account_balance()
        if balance:
            logger.info(f"💰 Saldo disponível: R$ {balance['available']:.2f} | Stake necessário: R$ {self.stake:.2f}")
            if balance['available'] < self.stake:
                logger.warning(f"⚠️ Saldo insuficiente! Disponível: R$ {balance['available']:.2f}, Necessário: R$ {self.stake:.2f}")
        
        # Contador informativo; futebol roda sem limite de quantidade.
        soccer_bets_count = sum(1 for b in self.active_bets.values() 
                              if b.sport == SportType.SOCCER and b.status == BetStatus.ACTIVE)
        logger.info(f"📈 Apostas ativas de futebol: {soccer_bets_count} (sem limite)")
        goal_line = self.soccer_config.get('entry_goal_line', 1.5)
        
        for match in matches[:20]:
            market_id = match['market_id']
            entry_runner_id = match.get('entry_runner_id')
            event_id = match.get('event_id')
            event_name = match.get('event_name', 'N/A')
            matches_checked += 1
            
            already_bet_on_event = False
            try:
                db_active_bets = self.db.get_active_bets()
                for db_bet in db_active_bets:
                    if db_bet.get('event_id') == event_id and db_bet.get('status') == 'ACTIVE':
                        logger.info(f"⚠️ Evento {event_name}: Já tem aposta ativa (Bet ID: {db_bet.get('bet_id', 'N/A')})")
                        already_bet_on_event = True
                        break
            except Exception as e:
                logger.debug(f"Erro ao verificar banco para evento {event_id}: {e}")
            
            if not already_bet_on_event:
                for bet in self.active_bets.values():
                    if bet.event_id == event_id and bet.status == BetStatus.ACTIVE:
                        logger.info(f"⚠️ Evento {event_name}: Já tem aposta ativa (Bet ID: {bet.bet_id})")
                        already_bet_on_event = True
                        break
            
            if already_bet_on_event:
                continue
            
            logger.debug(f"Verificando mercado {market_id}: {event_name}")
            is_pre_match = match.get('is_pre_match', False)

            # Verificar se tempo do jogo está disponível antes de apostar
            if self.soccer_config.get('require_game_time_to_bet', True) and not is_pre_match:
                market_start_time = match.get('market_start_time')
                game_minute = self.get_live_match_minute(market_id)
                time_available = (market_start_time is not None) or (game_minute is not None)
                if not time_available:
                    logger.warning(
                        f"⏱️ {event_name}: tempo do jogo indisponível (sem marketStartTime e sem feed ao vivo) "
                        f"— aposta bloqueada (require_game_time_to_bet=true)"
                    )
                    continue
                time_source = f"feed={game_minute}'" if game_minute is not None else "startTime"
                logger.info(f"⏱️ {event_name}: tempo disponível via {time_source} — prosseguindo")

            entry_conditions = self.check_soccer_entry_conditions(market_id, entry_runner_id, is_pre_match)
            
            if entry_conditions:
                matches_with_conditions += 1
                logger.info(f"✅ Condições Over {goal_line:.1f} atendidas para {event_name} - Price: {entry_conditions['price']:.2f}")
                bet_id = self.place_back_bet(
                    market_id=market_id,
                    selection_id=entry_conditions['selection_id'],
                    price=entry_conditions['price'],
                    stake=self.stake
                )
                
                if bet_id:
                    entry_time = datetime.now()
                    strategy_name = f"Back Over {goal_line:.1f}"
                    bet = ActiveBet(
                        bet_id=bet_id,
                        market_id=market_id,
                        event_id=match['event_id'],
                        sport=SportType.SOCCER,
                        strategy=strategy_name,
                        side="BACK",
                        selection_id=entry_conditions['selection_id'],
                        entry_price=entry_conditions['price'],
                        entry_time=entry_time,
                        stake=self.stake,
                        liability=0.0,
                        take_profit_pct=self.soccer_config['take_profit_pct'],
                        stop_loss_pct=self.soccer_config['stop_loss_pct'],
                    )
                    
                    self.active_bets[bet_id] = bet
                    self.stats['total_bets'] += 1
                    self.stats['soccer_bets'] += 1
                    
                    self.db.insert_bet({
                        'bet_id': bet_id,
                        'market_id': market_id,
                        'event_id': match['event_id'],
                        'event_name': match.get('event_name', ''),
                        'sport': SportType.SOCCER.name,
                        'strategy': strategy_name,
                        'side': "BACK",
                        'selection_id': entry_conditions['selection_id'],
                        'entry_price': entry_conditions['price'],
                        'entry_time': entry_time.isoformat(),
                        'stake': self.stake,
                        'liability': 0.0,
                        'take_profit_pct': self.soccer_config['take_profit_pct'],
                        'stop_loss_pct': self.soccer_config['stop_loss_pct'],
                        'status': 'ACTIVE',
                    })
                    
                    pre_match_mode = match.get('is_pre_match', False)
                    mode_text = "PRÉ-LIVE" if pre_match_mode else "AO VIVO"
                    logger.info(f"✓✓✓ NOVA APOSTA FUTEBOL {mode_text} (BACK Over {goal_line:.1f}): {match['event_name']} - Price {entry_conditions['price']:.2f} - Stake R$ {self.stake:.2f}")
                    logger.info(f"   → Estratégia seletiva (sem Under 1.5): jogo precisa chegar em 2+ gols totais")
                    
                    # Enviar notificação do Telegram
                    if self.telegram and self.telegram.enabled:
                        try:
                            balance = self.get_account_balance()
                            bet_info = {
                                'bet_id': bet_id,
                                'event_name': match.get('event_name', ''),
                                'sport': SportType.SOCCER.name,
                                'strategy': strategy_name,
                                'side': "BACK",
                                'entry_price': entry_conditions['price'],
                                'stake': self.stake,
                                'liability': 0.0,
                            }
                            self.telegram.notify_new_bet(bet_info, balance)
                        except Exception as e:
                            logger.warning(f"Erro ao enviar notificação do Telegram: {e}")

                else:
                    logger.warning(f"✗ Falha ao colocar aposta BACK para {match['event_name']}")
        
        if matches_checked > 0:
            logger.info(f"📊 Futebol: {matches_checked} mercados verificados, {matches_with_conditions} com condições atendidas")
        else:
            logger.debug("Nenhum mercado de futebol foi verificado nesta iteração")
    
    def check_hockey_entry_conditions(self, market_id: str) -> Optional[Dict]:
        """Verifica condições de entrada para hóquei"""
        try:
            market_book = self.api.list_market_book(
                market_ids=[market_id],
                price_projection={'priceData': ['EX_BEST_OFFERS']}
            )
            
            if not market_book:
                return None
            
            market = market_book[0]
            runners = market.get('runners', [])
            
            # Encontrar runner "Under" (1.5 ou 2.5)
            under_runner = None
            for runner in runners:
                runner_name = runner.get('runnerName', '').upper()
                if 'UNDER' in runner_name and ('1.5' in runner_name or '2.5' in runner_name):
                    under_runner = runner
                    break
            
            if not under_runner:
                return None
            
            # Obter odd atual
            available_to_lay = under_runner.get('ex', {}).get('availableToLay', [])
            if not available_to_lay:
                return None
            
            current_price = available_to_lay[0].get('price', 0)
            if current_price == 0:
                return None
            
            # Verificar se já temos aposta ativa neste mercado
            for bet in self.active_bets.values():
                if bet.market_id == market_id and bet.status == BetStatus.ACTIVE:
                    return None
            
            # Verificar limite de apostas
            hockey_bets_count = sum(1 for b in self.active_bets.values() 
                                   if b.sport == SportType.ICE_HOCKEY and b.status == BetStatus.ACTIVE)
            if hockey_bets_count >= self.max_bets_per_sport:
                return None
            
            return {
                'runner': under_runner,
                'price': current_price,
                'selection_id': under_runner.get('id'),
            }
        except Exception as e:
            logger.error(f"Erro ao verificar condições de hóquei: {e}")
            return None
    
    def process_hockey_strategy(self):
        """Processa estratégia de hóquei"""
        if not self.hockey_config['enabled']:
            return
        
        matches = self.find_live_hockey_matches()
        logger.info(f"Encontradas {len(matches)} partidas de hóquei ao vivo")
        
        for match in matches:
            market_id = match['market_id']
            entry_conditions = self.check_hockey_entry_conditions(market_id)
            
            if entry_conditions:
                # Fazer aposta LAY
                bet_id = self.place_lay_bet(
                    market_id=market_id,
                    selection_id=entry_conditions['selection_id'],
                    price=entry_conditions['price'],
                    stake=self.stake
                )
                
                if bet_id:
                    liability = self.stake * (entry_conditions['price'] - 1)
                    entry_time = datetime.now()
                    bet = ActiveBet(
                        bet_id=bet_id,
                        market_id=market_id,
                        event_id=match['event_id'],
                        sport=SportType.ICE_HOCKEY,
                        strategy="Lay Under Period",
                        side="LAY",
                        selection_id=entry_conditions['selection_id'],
                        entry_price=entry_conditions['price'],
                        entry_time=entry_time,
                        stake=self.stake,
                        liability=liability,
                        take_profit_pct=self.hockey_config['take_profit_pct'],
                        stop_loss_pct=self.hockey_config['stop_loss_pct'],
                    )
                    
                    self.active_bets[bet_id] = bet
                    self.stats['total_bets'] += 1
                    self.stats['hockey_bets'] += 1
                    
                    # Salvar no banco de dados
                    self.db.insert_bet({
                        'bet_id': bet_id,
                        'market_id': market_id,
                        'event_id': match['event_id'],
                        'event_name': match.get('event_name', ''),
                        'sport': SportType.ICE_HOCKEY.name,
                        'strategy': "Lay Under Period",
                        'side': "LAY",
                        'selection_id': entry_conditions['selection_id'],
                        'entry_price': entry_conditions['price'],
                        'entry_time': entry_time.isoformat(),
                        'stake': self.stake,
                        'liability': liability,
                        'take_profit_pct': self.hockey_config['take_profit_pct'],
                        'stop_loss_pct': self.hockey_config['stop_loss_pct'],
                        'status': 'ACTIVE',
                    })
                    
                    logger.info(f"✓ Nova aposta Hóquei: {match['event_name']} - Price {entry_conditions['price']}")
                    
                    # Enviar notificação do Telegram
                    if self.telegram and self.telegram.enabled:
                        try:
                            balance = self.get_account_balance()
                            bet_info = {
                                'bet_id': bet_id,
                                'event_name': match.get('event_name', ''),
                                'sport': SportType.ICE_HOCKEY.name,
                                'strategy': "Lay Under Period",
                                'side': "LAY",
                                'entry_price': entry_conditions['price'],
                                'stake': self.stake,
                                'liability': liability,
                            }
                            self.telegram.notify_new_bet(bet_info, balance)
                        except Exception as e:
                            logger.warning(f"Erro ao enviar notificação do Telegram: {e}")
    
    def process_tennis_strategy(self):
        """Processa estratégia de tênis"""
        if not self.tennis_config['enabled']:
            return
        
        matches = self.find_live_tennis_matches()
        logger.info(f"Encontradas {len(matches)} partidas de tênis ao vivo")
        entry_min_odd = self.tennis_config.get('entry_min_odd', 1.80)
        entry_max_odd = self.tennis_config.get('entry_max_odd', 2.20)
        max_concurrent_bets = self.tennis_config.get('max_concurrent_bets', 7)
        
        for match in matches:
            try:
                market_id = match['market_id']
                favorite = match.get('favorite_runner')
                favorite_odd = match.get('favorite_odd')
                
                if not favorite or not favorite_odd:
                    continue
                
                # Evitar duplicar aposta no mesmo jogo/mercado
                already_active = any(
                    bet.market_id == market_id and bet.status == BetStatus.ACTIVE
                    for bet in self.active_bets.values()
                )
                if already_active:
                    continue
                
                # Verificar limite
                tennis_bets_count = sum(1 for b in self.active_bets.values() 
                                      if b.sport == SportType.TENNIS and b.status == BetStatus.ACTIVE)
                if tennis_bets_count >= max_concurrent_bets:
                    logger.info(f"🎾 Limite de apostas de tênis atingido: {tennis_bets_count}/{max_concurrent_bets}")
                    continue
                
                # Verificar se o mercado está aberto e obter odd atual
                market_book = self.api.list_market_book(
                    market_ids=[market_id],
                    price_projection={'priceData': ['EX_BEST_OFFERS']}
                )
                
                if not market_book:
                    continue
                
                market = market_book[0]
                if market.get('status') != 'OPEN':
                    logger.debug(f"Mercado de tênis não está aberto: {market.get('status')}")
                    continue
                
                # Verificar se ainda há odds disponíveis
                runners = market.get('runners', [])
                
                # Obter ID do favorito - pode estar em diferentes campos
                favorite_id = favorite.get('id') or favorite.get('selectionId') or favorite.get('runnerId')
                
                if not favorite_id:
                    logger.warning(f"Mercado {market_id}: Favorito sem ID válido: {favorite}")
                    continue
                
                # Procurar runner no market book pelo ID
                current_runner = None
                for r in runners:
                    runner_id = r.get('id') or r.get('selectionId') or r.get('runnerId')
                    if runner_id == favorite_id:
                        current_runner = r
                        break
                
                if not current_runner:
                    logger.debug(f"Mercado {market_id}: Runner do favorito não encontrado no market book. Favorite ID: {favorite_id}")
                    continue
                
                available_to_back = current_runner.get('ex', {}).get('availableToBack', [])
                if not available_to_back or len(available_to_back) == 0:
                    logger.debug(f"Mercado {market_id}: Sem odds disponíveis para BACK no favorito")
                    continue
                
                current_price = available_to_back[0].get('price', 0)
                available_size = available_to_back[0].get('size', 0)
                
                if current_price == 0 or current_price < 1.01:
                    logger.debug(f"Mercado {market_id}: Preço inválido: {current_price}")
                    continue
                
                if current_price < entry_min_odd:
                    logger.debug(f"Mercado {market_id}: Odd abaixo da faixa: {current_price} < {entry_min_odd}")
                    continue
                
                if current_price > entry_max_odd:
                    logger.debug(f"Mercado {market_id}: Odd muito alta: {current_price} > {entry_max_odd}")
                    continue
                
                # Verificar liquidez suficiente
                if available_size < self.stake:
                    logger.debug(f"Mercado {market_id}: Liquidez insuficiente: {available_size} < {self.stake}")
                    continue
                
                # Validar selection_id antes de fazer aposta
                # O selectionId deve vir do runner atual no market book
                selection_id = current_runner.get('id')
                if not selection_id:
                    # Tentar outros campos
                    selection_id = current_runner.get('selectionId') or current_runner.get('runnerId')
                
                if not selection_id:
                    logger.error(f"Mercado {market_id}: Não foi possível obter selection_id válido do runner atual")
                    logger.debug(f"Runner atual: {current_runner}")
                    continue
                
                try:
                    # Tentar converter para int para validar
                    selection_id_int = int(selection_id)
                    if selection_id_int <= 0:
                        raise ValueError("selection_id deve ser positivo")
                except (ValueError, TypeError) as e:
                    logger.error(f"Mercado {market_id}: selection_id inválido para conversão: {selection_id} - {e}")
                    continue
                
                # Verificar novamente se o mercado ainda está aberto (pode ter mudado)
                if market.get('status') != 'OPEN':
                    logger.debug(f"Mercado {market_id}: Status mudou para {market.get('status')} antes da aposta")
                    continue
                
                # Verificar novamente se há liquidez (pode ter mudado)
                available_to_back_check = current_runner.get('ex', {}).get('availableToBack', [])
                if not available_to_back_check or len(available_to_back_check) == 0:
                    logger.debug(f"Mercado {market_id}: Liquidez desapareceu antes da aposta")
                    continue
                
                current_price_check = available_to_back_check[0].get('price', 0)
                if current_price_check != current_price:
                    logger.debug(f"Mercado {market_id}: Preço mudou de {current_price} para {current_price_check}")
                    current_price = current_price_check
                
                logger.info(f"✓ Tentando aposta BACK em tênis: Market {market_id}, Selection {selection_id_int}, Price {current_price:.2f}, Size {available_size:.2f}")
                
                # Fazer aposta BACK no favorito
                bet_id = self.place_back_bet(
                    market_id=market_id,
                    selection_id=str(selection_id_int),
                    price=current_price,
                    stake=self.stake
                )
                
                if bet_id:
                    entry_time = datetime.now()
                    strategy_name = "Back Favorite Drift"
                    bet = ActiveBet(
                        bet_id=bet_id,
                        market_id=market_id,
                        event_id=match['event_id'],
                        sport=SportType.TENNIS,
                        strategy=strategy_name,
                        side="BACK",
                        selection_id=str(selection_id_int),
                        entry_price=current_price,
                        entry_time=entry_time,
                        stake=self.stake,
                        liability=0,  # BACK não tem responsabilidade
                        take_profit_pct=self.tennis_config['take_profit_pct'],
                        stop_loss_pct=self.tennis_config['stop_loss_pct'],
                    )
                    
                    self.active_bets[bet_id] = bet
                    self.stats['total_bets'] += 1
                    self.stats['tennis_bets'] += 1
                    
                    # Salvar no banco de dados
                    self.db.insert_bet({
                        'bet_id': bet_id,
                        'market_id': market_id,
                        'event_id': match['event_id'],
                        'event_name': match.get('event_name', ''),
                        'sport': SportType.TENNIS.name,
                        'strategy': strategy_name,
                        'side': "BACK",
                        'selection_id': str(selection_id_int),
                        'entry_price': current_price,
                        'entry_time': entry_time.isoformat(),
                        'stake': self.stake,
                        'liability': 0,
                        'take_profit_pct': self.tennis_config['take_profit_pct'],
                        'stop_loss_pct': self.tennis_config['stop_loss_pct'],
                        'status': 'ACTIVE',
                    })
                    
                    logger.info(f"✓ Nova aposta Tênis: {match['event_name']} - Favorite {current_price}")
                    
                    # Enviar notificação do Telegram
                    if self.telegram and self.telegram.enabled:
                        try:
                            balance = self.get_account_balance()
                            bet_info = {
                                'bet_id': bet_id,
                                'event_name': match.get('event_name', ''),
                                'sport': SportType.TENNIS.name,
                                'strategy': strategy_name,
                                'side': "BACK",
                                'entry_price': current_price,
                                'stake': self.stake,
                                'liability': 0.0,
                            }
                            self.telegram.notify_new_bet(bet_info, balance)
                        except Exception as e:
                            logger.warning(f"Erro ao enviar notificação do Telegram: {e}")
            except Exception as e:
                logger.error(f"Erro ao processar partida de tênis {match.get('event_name', 'N/A')}: {e}")
                continue
    
    def find_pre_match_markets(self) -> List[Dict]:
        """Encontra mercados pré-jogo para trading (Match Odds)"""
        try:
            from datetime import datetime, timedelta
            
            # Buscar mercados Match Odds pré-jogo (inPlay=False)
            filter_dict = {
                'eventTypeIds': ['1'],  # Soccer
                'marketTypeCodes': ['MATCH_ODDS'],
                'inPlay': False,  # Apenas pré-jogo
            }
            
            markets = self.api.list_market_catalogue(
                filter_dict=filter_dict,
                market_projection=['MARKET_DESCRIPTION', 'RUNNER_DESCRIPTION', 'EVENT', 'MARKET_START_TIME'],
                max_results=100
            )
            
            if not markets:
                return []
            
            valid_markets = []
            now = datetime.now()
            min_hours = self.pre_match_trading_config['min_hours_before_start']
            max_hours = self.pre_match_trading_config['max_hours_before_start']
            
            for market in markets:
                event = market.get('event', {})
                market_start_time = market.get('marketStartTime')
                
                if not market_start_time:
                    continue
                
                try:
                    start_time = datetime.fromisoformat(market_start_time.replace('Z', '+00:00'))
                    # Converter para timezone local se necessário
                    if start_time.tzinfo:
                        start_time = start_time.astimezone().replace(tzinfo=None)
                    
                    hours_until_start = (start_time - now).total_seconds() / 3600
                    
                    # Verificar se está na janela de tempo permitida
                    if min_hours <= hours_until_start <= max_hours:
                        market_id = market.get('marketId')
                        if market_id:
                            valid_markets.append({
                                'market_id': market_id,
                                'event_id': event.get('id'),
                                'event_name': event.get('name', ''),
                                'start_time': start_time,
                                'hours_until_start': hours_until_start,
                                'market': market,
                            })
                except Exception as e:
                    logger.debug(f"Erro ao processar tempo do mercado: {e}")
                    continue
            
            return valid_markets
        except Exception as e:
            logger.error(f"Erro ao buscar mercados pré-jogo: {e}")
            return []
    
    def check_pre_match_entry_conditions(self, market_id: str, selection_id: str) -> Optional[Dict]:
        """Verifica condições de entrada para trading pré-jogo"""
        try:
            market_book = self.api.list_market_book(
                market_ids=[market_id],
                price_projection={'priceData': ['EX_BEST_OFFERS', 'EX_TRADED']}
            )
            
            if not market_book:
                return None
            
            market = market_book[0]
            
            # Verificar se mercado está aberto
            if market.get('status') != 'OPEN':
                return None
            
            # Verificar se já começou (não deve estar inPlay)
            if market.get('inPlay', False):
                return None
            
            runners = market.get('runners', [])
            target_runner = None
            
            for runner in runners:
                runner_id = runner.get('id') or runner.get('selectionId')
                if str(runner_id) == str(selection_id):
                    target_runner = runner
                    break
            
            if not target_runner:
                return None
            
            # Verificar odds disponíveis
            available_to_back = target_runner.get('ex', {}).get('availableToBack', [])
            if not available_to_back:
                return None
            
            current_price = available_to_back[0].get('price', 0)
            available_size = available_to_back[0].get('size', 0)
            
            if current_price < self.pre_match_trading_config['min_odd'] or \
               current_price > self.pre_match_trading_config['max_odd']:
                return None
            
            if available_size < self.pre_match_trading_config['stake']:
                return None
            
            # Verificar volume do mercado (total matched)
            total_matched = market.get('totalMatched', 0)
            if total_matched < self.pre_match_trading_config['min_market_volume']:
                return None
            
            # Verificar se já tem aposta ativa neste mercado
            for bet in self.active_bets.values():
                if bet.market_id == market_id and bet.status == BetStatus.ACTIVE:
                    if bet.strategy == "Pre-Match Trading":
                        return None
            
            return {
                'runner': target_runner,
                'price': current_price,
                'selection_id': selection_id,
                'market_volume': total_matched,
            }
        except Exception as e:
            logger.error(f"Erro ao verificar condições pré-jogo: {e}")
            return None
    
    def process_pre_match_trading_strategy(self):
        """Processa estratégia de trading pré-jogo (Green Book)"""
        if not self.pre_match_trading_config['enabled']:
            return
        
        logger.info("🎯 Buscando mercados pré-jogo para trading...")
        markets = self.find_pre_match_markets()
        logger.info(f"📊 Encontrados {len(markets)} mercados pré-jogo na janela de tempo")
        
        if len(markets) == 0:
            return
        
        # Verificar saldo
        balance = self.get_account_balance()
        if balance and balance['available'] < self.pre_match_trading_config['stake']:
            logger.warning(f"⚠️ Saldo insuficiente para trading pré-jogo. Disponível: R$ {balance['available']:.2f}")
            return
        
        # Limitar a 10 mercados por ciclo
        for market_info in markets[:10]:
            try:
                market_id = market_info['market_id']
                event_name = market_info['event_name']
                market = market_info['market']
                
                # Obter runners do mercado
                runners = market.get('runners', [])
                if len(runners) < 2:
                    continue
                
                # Escolher runner com odds dentro da faixa (preferir odds médias)
                best_runner = None
                best_price = None
                
                for runner in runners:
                    runner_id = runner.get('selectionId') or runner.get('id')
                    runner_name = runner.get('runnerName', '')
                    
                    # Verificar condições de entrada
                    entry_conditions = self.check_pre_match_entry_conditions(market_id, str(runner_id))
                    if entry_conditions:
                        price = entry_conditions['price']
                        # Preferir odds entre 1.80 e 2.50 (mais movimento esperado)
                        if 1.80 <= price <= 2.50:
                            if best_runner is None or abs(price - 2.0) < abs(best_price - 2.0):
                                best_runner = runner
                                best_price = price
                                best_entry = entry_conditions
                
                if best_runner and best_entry:
                    # Fazer BACK
                    bet_id = self.place_back_bet(
                        market_id=market_id,
                        selection_id=str(best_entry['selection_id']),
                        price=best_price,
                        stake=self.pre_match_trading_config['stake']
                    )
                    
                    if bet_id:
                        entry_time = datetime.now()
                        bet = ActiveBet(
                            bet_id=bet_id,
                            market_id=market_id,
                            event_id=market_info['event_id'],
                            sport=SportType.SOCCER,  # Usar SOCCER como base
                            strategy="Pre-Match Trading",
                            side="BACK",
                            selection_id=str(best_entry['selection_id']),
                            entry_price=best_price,
                            entry_time=entry_time,
                            stake=self.pre_match_trading_config['stake'],
                            liability=0.0,
                            take_profit_pct=self.pre_match_trading_config['take_profit_pct'],
                            stop_loss_pct=self.pre_match_trading_config['stop_loss_pct'],
                        )
                        
                        self.active_bets[bet_id] = bet
                        self.stats['total_bets'] += 1
                        self.stats['soccer_bets'] += 1
                        
                        # Salvar no banco
                        self.db.insert_bet({
                            'bet_id': bet_id,
                            'market_id': market_id,
                            'event_id': market_info['event_id'],
                            'event_name': event_name,
                            'sport': SportType.SOCCER.name,
                            'strategy': "Pre-Match Trading",
                            'side': "BACK",
                            'selection_id': str(best_entry['selection_id']),
                            'entry_price': best_price,
                            'entry_time': entry_time.isoformat(),
                            'stake': self.pre_match_trading_config['stake'],
                            'liability': 0.0,
                            'take_profit_pct': self.pre_match_trading_config['take_profit_pct'],
                            'stop_loss_pct': self.pre_match_trading_config['stop_loss_pct'],
                            'status': 'ACTIVE',
                        })
                        
                        runner_name = best_runner.get('runnerName', 'N/A')
                        logger.info(f"✓✓✓ NOVA APOSTA PRÉ-JOGO (Green Book): {event_name}")
                        logger.info(f"   → BACK {runner_name} @ {best_price:.2f} - Stake R$ {self.pre_match_trading_config['stake']:.2f}")
                        logger.info(f"   → Monitorando para fechar com LAY quando odds mudarem")
                        
                        # Notificação Telegram
                        if self.telegram and self.telegram.enabled:
                            try:
                                bet_info = {
                                    'bet_id': bet_id,
                                    'event_name': event_name,
                                    'sport': 'Pre-Match Trading',
                                    'strategy': "Pre-Match Trading",
                                    'side': "BACK",
                                    'entry_price': best_price,
                                    'stake': self.pre_match_trading_config['stake'],
                                    'liability': 0.0,
                                }
                                self.telegram.notify_new_bet(bet_info, balance)
                            except Exception as e:
                                logger.warning(f"Erro ao enviar notificação: {e}")
            except Exception as e:
                logger.error(f"Erro ao processar mercado pré-jogo: {e}")
                continue
    
    def monitor_active_bets(self):
        """Monitora e gerencia apostas ativas"""
        bets_to_remove = []
        
        for bet_id, bet in self.active_bets.items():
            if bet.status == BetStatus.ACTIVE:
                # Verificar se é aposta pré-jogo que precisa ser fechada antes do jogo começar
                if bet.strategy == "Pre-Match Trading":
                    # Verificar se o jogo está prestes a começar
                    match_time = self.get_match_time(bet.market_id)
                    if match_time is not None and match_time >= 0:
                        # Jogo começou ou está prestes a começar
                        close_minutes = self.pre_match_trading_config['close_before_start_minutes']
                        if match_time >= -close_minutes/60:  # Converter minutos para horas
                            logger.warning(f"⏰ Aposta pré-jogo {bet_id}: Jogo começando em breve, fechando posição...")
                            # Fazer LAY para fechar (green book)
                            self.close_pre_match_bet_with_lay(bet)
                            continue
                
                closed = self.check_and_close_bet(bet)
                if closed:
                    bets_to_remove.append(bet_id)
        
        # Remover apostas fechadas (opcional - manter histórico)
        # for bet_id in bets_to_remove:
        #     del self.active_bets[bet_id]
    
    def close_pre_match_bet_with_lay(self, bet: ActiveBet) -> bool:
        """Fecha aposta pré-jogo fazendo LAY (green book)"""
        try:
            # Obter odds atuais para LAY
            market_book = self.api.list_market_book(
                market_ids=[bet.market_id],
                price_projection={'priceData': ['EX_BEST_OFFERS']}
            )
            
            if not market_book:
                return False
            
            runners = market_book[0].get('runners', [])
            target_runner = None
            
            for runner in runners:
                runner_id = runner.get('id') or runner.get('selectionId')
                if str(runner_id) == str(bet.selection_id):
                    target_runner = runner
                    break
            
            if not target_runner:
                return False
            
            available_to_lay = target_runner.get('ex', {}).get('availableToLay', [])
            if not available_to_lay:
                return False
            
            lay_price = available_to_lay[0].get('price', 0)
            if lay_price <= 1.0:
                return False
            
            # Calcular stake do LAY para fazer green book
            # Para fechar BACK: lay_stake = (back_stake * back_price) / lay_price
            lay_stake = (bet.stake * bet.entry_price) / lay_price
            
            # Fazer LAY
            lay_bet_id = self.place_lay_bet(
                market_id=bet.market_id,
                selection_id=str(bet.selection_id),
                price=lay_price,
                stake=lay_stake
            )
            
            if lay_bet_id:
                # Calcular lucro/prejuízo
                profit_pct = ((bet.entry_price - lay_price) / bet.entry_price) * 100
                
                bet.status = BetStatus.CLOSED_PROFIT if profit_pct > 0 else BetStatus.CLOSED_LOSS
                bet.close_reason = f"Green Book (Pré-Jogo): {profit_pct:.2f}%"
                bet.profit_loss = profit_pct
                
                if profit_pct > 0:
                    self.stats['profit_bets'] += 1
                else:
                    self.stats['loss_bets'] += 1
                
                self.stats['total_profit'] += (bet.stake * profit_pct / 100)
                
                # Atualizar banco
                self.db.close_bet(
                    bet.bet_id,
                    bet.status.name,
                    profit_pct,
                    bet.close_reason,
                    lay_price
                )
                
                logger.info(f"✓ Green Book fechado: {bet.sport.value} - {profit_pct:.2f}% (LAY @ {lay_price:.2f})")
                return True
            
            return False
        except Exception as e:
            logger.error(f"Erro ao fechar aposta pré-jogo: {e}")
            return False
    
    def get_account_balance(self):
        """Obtém o saldo da conta Betfair"""
        try:
            funds = self.api.get_account_funds()
            logger.debug(f"Resposta get_account_funds: {funds}")
            
            if funds:
                available = funds.get('availableToBetBalance', 0)
                total = funds.get('totalBalance', 0)
                exposure = funds.get('exposure', 0)
                
                balance_info = {
                    'available': float(available) if available else 0.0,
                    'total': float(total) if total else 0.0,
                    'exposure': float(exposure) if exposure else 0.0
                }
                logger.debug(f"Saldo extraído: {balance_info}")
                return balance_info
            else:
                logger.warning("get_account_funds retornou None ou vazio")
        except Exception as e:
            logger.error(f"Erro ao obter saldo da conta: {e}", exc_info=True)
        return None
    
    def print_stats(self):
        """Imprime estatísticas do bot"""
        active_count = sum(1 for b in self.active_bets.values() if b.status == BetStatus.ACTIVE)
        
        # Obter saldo da conta
        logger.debug("Buscando saldo da conta...")
        balance = self.get_account_balance()
        logger.debug(f"Resultado get_account_balance: {balance}")
        
        logger.info("=" * 60)
        logger.info("ESTATÍSTICAS DO BOT")
        logger.info("=" * 60)
        logger.info(f"Total de apostas: {self.stats['total_bets']}")
        logger.info(f"Apostas ativas: {active_count}")
        logger.info(f"Apostas com lucro: {self.stats['profit_bets']}")
        logger.info(f"Apostas com perda: {self.stats['loss_bets']}")
        logger.info(f"Lucro total: R$ {self.stats['total_profit']:.2f}")
        logger.info(f"Futebol: {self.stats['soccer_bets']} | Hóquei: {self.stats['hockey_bets']} | Tênis: {self.stats['tennis_bets']}")
        
        if balance:
            logger.info(f"💰 Saldo disponível: R$ {balance['available']:.2f}")
            logger.info(f"💰 Saldo total: R$ {balance['total']:.2f}")
            if balance['exposure'] > 0:
                logger.info(f"💰 Exposição: R$ {balance['exposure']:.2f}")
            
            # Salvar saldo no banco de dados
            self.db.save_balance(
                balance['available'],
                balance['total'],
                balance.get('exposure', 0)
            )
        else:
            logger.warning("⚠️ Não foi possível obter saldo da conta")
        
        logger.info("=" * 60)
    
    # =========================================================================
    # ESTRATÉGIA: LAY DE EMPATE COM SAÍDA POR MOVIMENTO DE ODDS
    # =========================================================================

    def _init_lay_draw_bank(self, balance: float):
        """Inicializa ou reseta o controle de banca para o dia."""
        today = datetime.now().day
        if self.lay_draw_initial_balance is None:
            self.lay_draw_initial_balance = balance
            logger.info(f"💰 [LayDraw] Banca inicial registrada: R$ {balance:.2f}")

        if self.lay_draw_last_day != today:
            self.lay_draw_daily_start_balance = balance
            self.lay_draw_last_day = today
            self.lay_draw_paused_today = False
            logger.info(f"📅 [LayDraw] Novo dia — banca inicial do dia: R$ {balance:.2f}")

    def _check_lay_draw_bank_limits(self, balance: float) -> bool:
        """
        Verifica limites de banca. Retorna True se pode operar, False se deve parar.
        """
        cfg = self.lay_draw_config

        if self.lay_draw_stopped_permanently:
            logger.warning("🚫 [LayDraw] Bot parado permanentemente (limite total atingido).")
            return False

        if cfg['daily_loss_limit_pct'] <= 0:
            self.lay_draw_paused_today = False  # Limite diário desativado — nunca pausar por isso
        if self.lay_draw_paused_today:
            logger.warning("⏸️ [LayDraw] Operações pausadas hoje (limite diário atingido).")
            return False

        if self.lay_draw_initial_balance and balance < self.lay_draw_initial_balance * (1 - cfg['total_loss_limit_pct'] / 100):
            self.lay_draw_stopped_permanently = True
            msg = (f"🚨 [LayDraw] BANCA CAIU {cfg['total_loss_limit_pct']:.0f}% DO TOTAL! "
                   f"Inicial: R${self.lay_draw_initial_balance:.2f} | Atual: R${balance:.2f} — BOT PARADO.")
            logger.error(msg)
            if self.telegram:
                self.telegram.send_message(msg)
            return False

        # Limite diário: só aplica se daily_loss_limit_pct > 0 (0 = desativado)
        if cfg['daily_loss_limit_pct'] > 0 and self.lay_draw_daily_start_balance:
            if balance < self.lay_draw_daily_start_balance * (1 - cfg['daily_loss_limit_pct'] / 100):
                self.lay_draw_paused_today = True
                msg = (f"⚠️ [LayDraw] Banca caiu {cfg['daily_loss_limit_pct']:.0f}% no dia! "
                       f"Início do dia: R${self.lay_draw_daily_start_balance:.2f} | Atual: R${balance:.2f} — pausando hoje.")
                logger.warning(msg)
                if self.telegram:
                    self.telegram.send_message(msg)
                return False

        return True

    def find_live_match_odds_markets(self) -> List[Dict]:
        """Busca mercados MATCH_ODDS ao vivo (para Lay Draw)."""
        try:
            filter_dict = {
                'eventTypeIds': ['1'],
                'marketTypeCodes': ['MATCH_ODDS'],
                'inPlay': True,
            }
            markets = self.api.list_market_catalogue(
                filter_dict=filter_dict,
                market_projection=['MARKET_DESCRIPTION', 'RUNNER_DESCRIPTION', 'EVENT'],
                max_results=100
            )
            if not markets:
                logger.debug("[LayDraw] Nenhum mercado MATCH_ODDS ao vivo encontrado.")
                return []

            result = []
            for market in markets:
                market_id = market.get('marketId')
                event = market.get('event', {})
                event_id = event.get('id')
                event_name = event.get('name', 'N/A')
                runners = market.get('runners', [])

                draw_runner = None
                for r in runners:
                    name = r.get('runnerName', '').upper()
                    if 'DRAW' in name or name == 'THE DRAW' or name == 'EMPATE':
                        draw_runner = r
                        break
                # fallback: 3º runner costuma ser o empate no MATCH_ODDS
                if not draw_runner and len(runners) >= 3:
                    draw_runner = runners[2]

                if not draw_runner:
                    continue

                runner_id = draw_runner.get('selectionId') or draw_runner.get('id')
                if runner_id:
                    try:
                        runner_id = int(runner_id)
                    except (ValueError, TypeError):
                        continue

                if not runner_id:
                    continue

                result.append({
                    'market_id': market_id,
                    'event_id': event_id,
                    'event_name': event_name,
                    'draw_runner_id': runner_id,
                    'draw_runner_name': draw_runner.get('runnerName', 'The Draw'),
                })

            logger.info(f"[LayDraw] {len(result)} mercados MATCH_ODDS encontrados.")
            return result

        except Exception as e:
            logger.error(f"[LayDraw] Erro ao buscar MATCH_ODDS: {e}")
            return []

    def check_lay_draw_entry(self, market: Dict) -> Optional[Dict]:
        """
        Verifica condições de entrada para Lay Draw:
        - Odd do empate entre min_odd e max_odd
        - Jogo nos primeiros entry_max_minute minutos
        - Liquidez suficiente
        - Sem aposta ativa neste evento
        """
        cfg = self.lay_draw_config
        market_id = market['market_id']
        event_name = market['event_name']
        draw_runner_id = market['draw_runner_id']

        # Verificar duplicata na memória
        for bet in self.active_bets.values():
            if bet.event_id == market['event_id'] and bet.strategy == 'Lay Draw' and bet.status == BetStatus.ACTIVE:
                logger.debug(f"[LayDraw] {event_name}: já tem aposta ativa neste jogo.")
                return None

        # Verificar minuto do jogo
        match_time = self.get_match_time(market_id)
        if match_time is None:
            logger.debug(f"[LayDraw] {event_name}: não foi possível obter minuto do jogo.")
            return None
        if match_time > cfg['entry_max_minute']:
            logger.debug(f"[LayDraw] {event_name}: jogo muito avançado ({match_time} min > {cfg['entry_max_minute']} min).")
            return None

        # Buscar odds atuais
        try:
            market_book = self.api.list_market_book(
                market_ids=[market_id],
                price_projection={'priceData': ['EX_BEST_OFFERS']}
            )
        except Exception as e:
            logger.debug(f"[LayDraw] Erro ao buscar market book {market_id}: {e}")
            return None

        if not market_book:
            return None

        mb = market_book[0]
        if mb.get('status') != 'OPEN':
            return None

        total_matched = mb.get('totalMatched', 0) or 0

        # Encontrar runner do empate
        draw_runner = None
        for r in mb.get('runners', []):
            rid = r.get('id') or r.get('selectionId')
            try:
                if int(rid) == draw_runner_id:
                    draw_runner = r
                    break
            except (TypeError, ValueError):
                continue

        if not draw_runner:
            logger.debug(f"[LayDraw] {event_name}: runner do empate não encontrado no book.")
            return None

        # Odd atual do empate para LAY
        available_to_lay = draw_runner.get('ex', {}).get('availableToLay', [])
        if not available_to_lay:
            logger.debug(f"[LayDraw] {event_name}: sem liquidez para LAY no empate.")
            return None

        draw_odd = available_to_lay[0].get('price', 0)
        lay_size = available_to_lay[0].get('size', 0)

        if draw_odd <= 1.0:
            return None

        # Verificar faixa de odd
        if not (cfg['min_odd'] <= draw_odd <= cfg['max_odd']):
            logger.debug(f"[LayDraw] {event_name}: odd do empate {draw_odd:.2f} fora da faixa [{cfg['min_odd']}-{cfg['max_odd']}].")
            return None

        # Verificar liquidez do mercado
        if total_matched < cfg['min_market_volume']:
            logger.debug(f"[LayDraw] {event_name}: liquidez insuficiente (R${total_matched:.0f} < R${cfg['min_market_volume']:.0f}).")
            return None

        logger.info(f"✅ [LayDraw] {event_name} — odd empate {draw_odd:.2f} | min {match_time} | vol R${total_matched:.0f}")
        return {
            'market_id': market_id,
            'event_id': market['event_id'],
            'event_name': event_name,
            'draw_runner_id': draw_runner_id,
            'draw_odd': draw_odd,
            'lay_size': lay_size,
            'match_time': match_time,
            'total_matched': total_matched,
        }

    def close_lay_draw_position(self, bet: 'ActiveBet', reason: str) -> bool:
        """
        Fecha a posição de Lay Draw colocando BACK no empate para fazer green.
        Fórmula: back_stake = (lay_stake * lay_odd) / back_odd
        Profit  = lay_stake * (1 - lay_odd / back_odd) * (1 - commission/100)
        """
        cfg = self.lay_draw_config
        try:
            market_book = self.api.list_market_book(
                market_ids=[bet.market_id],
                price_projection={'priceData': ['EX_BEST_OFFERS']}
            )
            if not market_book:
                logger.warning(f"[LayDraw] Não conseguiu market book para fechar {bet.bet_id}")
                return False

            mb = market_book[0]
            if mb.get('status') not in ('OPEN',):
                # Mercado fechado/suspenso — registrar como encerrado
                logger.warning(f"[LayDraw] Mercado {bet.market_id} não está aberto (status: {mb.get('status')}) — registrando fechamento.")
                self._record_lay_draw_close(bet, bet.entry_price, reason, force=True)
                return True

            draw_runner = None
            for r in mb.get('runners', []):
                rid = r.get('id') or r.get('selectionId')
                try:
                    if int(rid) == int(bet.selection_id):
                        draw_runner = r
                        break
                except (TypeError, ValueError):
                    continue

            if not draw_runner:
                logger.warning(f"[LayDraw] Runner do empate não encontrado para fechar {bet.bet_id}")
                return False

            # Usar availableToBack para o BACK (fechar o lay)
            available_to_back = draw_runner.get('ex', {}).get('availableToBack', [])
            if not available_to_back:
                logger.warning(f"[LayDraw] Sem liquidez para BACK ao fechar {bet.bet_id}")
                return False

            back_odd = available_to_back[0].get('price', 0)
            if back_odd <= 1.0:
                return False

            # Calcular stake do back para green
            back_stake = round((bet.stake * bet.entry_price) / back_odd, 2)
            back_stake = max(back_stake, 2.0)  # mínimo da Betfair

            # Calcular P&L
            gross_profit = bet.stake * (1 - bet.entry_price / back_odd)
            commission_val = max(gross_profit, 0) * (cfg['commission'] / 100)
            net_profit = gross_profit - commission_val

            logger.info(f"📤 [LayDraw] Fechando {bet.bet_id} — BACK @ {back_odd:.2f} | back_stake={back_stake:.2f} | P&L bruto R${gross_profit:.2f} | líquido R${net_profit:.2f} | motivo: {reason}")

            back_bet_id = self.place_back_bet(
                market_id=bet.market_id,
                selection_id=str(bet.selection_id),
                price=back_odd,
                stake=back_stake,
            )

            if back_bet_id:
                self._record_lay_draw_close(bet, back_odd, reason, net_profit=net_profit)
                return True
            else:
                logger.error(f"[LayDraw] Falha ao colocar BACK para fechar {bet.bet_id}")
                return False

        except Exception as e:
            logger.error(f"[LayDraw] Erro ao fechar posição {bet.bet_id}: {e}", exc_info=True)
            return False

    def _record_lay_draw_close(self, bet: 'ActiveBet', exit_price: float, reason: str,
                                net_profit: Optional[float] = None, force: bool = False):
        """Registra o fechamento de uma aposta Lay Draw no banco e Telegram."""
        if net_profit is None:
            gross = bet.stake * (1 - bet.entry_price / exit_price) if exit_price > 0 else 0
            net_profit = gross * (1 - self.lay_draw_config['commission'] / 100) if gross > 0 else gross

        won = net_profit >= 0
        bet.status = BetStatus.CLOSED_PROFIT if won else BetStatus.CLOSED_LOSS
        bet.close_reason = reason
        bet.profit_loss = net_profit
        bet.current_price = exit_price

        self.stats['profit_bets' if won else 'loss_bets'] += 1
        self.stats['total_profit'] += net_profit

        self.db.close_bet(
            bet.bet_id,
            bet.status.name,
            net_profit,
            reason,
            exit_price,
            actual_profit_brl=net_profit,
        )

        emoji = "✅" if won else "❌"
        event_info = f"[{bet.event_id}]"
        msg = (f"{emoji} [LayDraw] {event_info} Saída: {reason}\n"
               f"   Entrada: {bet.entry_price:.2f} | Saída: {exit_price:.2f}\n"
               f"   Stake: R${bet.stake:.2f} | Resultado: R${net_profit:+.2f}")
        logger.info(msg)
        if self.telegram:
            self.telegram.send_message(msg)

    def monitor_lay_draw_bets(self):
        """
        Monitora apostas Lay Draw ativas. A cada ciclo verifica:
        - Take Profit: odd do empate >= take_profit_odd  → fechar com lucro
        - Stop Loss:   odd do empate <= stop_loss_odd    → fechar com perda
        - Timeout:     minuto estimado >= exit_max_minute → fechar posição
        """
        cfg = self.lay_draw_config

        for bet_id, bet in list(self.active_bets.items()):
            if bet.strategy != 'Lay Draw' or bet.status != BetStatus.ACTIVE:
                continue

            try:
                market_book = self.api.list_market_book(
                    market_ids=[bet.market_id],
                    price_projection={'priceData': ['EX_BEST_OFFERS']}
                )
                if not market_book:
                    continue

                mb = market_book[0]
                status = mb.get('status')

                # Mercado fechado inesperadamente
                if status == 'CLOSED':
                    logger.warning(f"[LayDraw] Mercado {bet.market_id} FECHADO inesperadamente — encerrando aposta.")
                    self._record_lay_draw_close(bet, bet.entry_price, "Mercado fechado", force=True)
                    continue

                if status != 'OPEN':
                    continue

                draw_runner = None
                for r in mb.get('runners', []):
                    rid = r.get('id') or r.get('selectionId')
                    try:
                        if int(rid) == int(bet.selection_id):
                            draw_runner = r
                            break
                    except (TypeError, ValueError):
                        continue

                if not draw_runner:
                    continue

                # Odd atual do empate (usar availableToBack para saber o preço de fechar)
                atb = draw_runner.get('ex', {}).get('availableToBack', [])
                if not atb:
                    continue
                current_odd = atb[0].get('price', 0)
                if current_odd <= 1.0:
                    continue

                bet.current_price = current_odd
                elapsed_min = (datetime.now() - bet.entry_time).total_seconds() / 60

                # P&L estimado (antes da comissão)
                gross = bet.stake * (1 - bet.entry_price / current_odd)
                net = gross * (1 - cfg['commission'] / 100) if gross > 0 else gross

                logger.debug(
                    f"[LayDraw] {bet.bet_id} | odd empate atual: {current_odd:.2f} "
                    f"(entrada {bet.entry_price:.2f}) | ~{elapsed_min:.0f} min | P&L R${net:+.2f}"
                )

                # ---- Take Profit ----
                if current_odd >= cfg['take_profit_odd']:
                    logger.info(f"💰 [LayDraw] Take Profit! Odd empate {current_odd:.2f} >= {cfg['take_profit_odd']}")
                    self.close_lay_draw_position(bet, f"Take Profit @ {current_odd:.2f}")
                    continue

                # ---- Stop Loss (só se habilitado e se prejuízo >= stop_loss_min_loss_brl) ----
                if cfg.get('enable_stop_loss', False) and current_odd <= cfg['stop_loss_odd']:
                    min_loss = cfg.get('stop_loss_min_loss_brl', 5.0)
                    if net <= -min_loss:
                        logger.warning(f"🛑 [LayDraw] Stop Loss! Odd empate {current_odd:.2f} <= {cfg['stop_loss_odd']} | prejuízo R${net:.2f} >= R${min_loss:.2f}")
                        self.close_lay_draw_position(bet, f"Stop Loss @ {current_odd:.2f}")
                    continue

                # ---- Timeout no intervalo (só se habilitado no config) ----
                if cfg.get('enable_timeout_exit', False):
                    match_time = self.get_match_time(bet.market_id)
                    if match_time and match_time >= cfg['exit_max_minute']:
                        logger.info(f"⏰ [LayDraw] Timeout! Minuto {match_time} >= {cfg['exit_max_minute']} — fechando posição.")
                        self.close_lay_draw_position(bet, f"Timeout {match_time} min")
                        continue

            except Exception as e:
                logger.error(f"[LayDraw] Erro ao monitorar {bet_id}: {e}")

    def process_lay_draw_strategy(self):
        """Loop principal da estratégia Lay Draw."""
        if not self.lay_draw_config['enabled']:
            return

        cfg = self.lay_draw_config

        balance_info = self.get_account_balance()
        if not balance_info:
            logger.warning("[LayDraw] Não foi possível obter saldo — pulando ciclo.")
            return

        balance = balance_info['available']
        self._init_lay_draw_bank(balance)

        if not self._check_lay_draw_bank_limits(balance):
            return

        # Contar apostas Lay Draw ativas
        active_lay_draw = sum(
            1 for b in self.active_bets.values()
            if b.strategy == 'Lay Draw' and b.status == BetStatus.ACTIVE
        )

        if active_lay_draw >= cfg['max_concurrent_bets']:
            logger.debug(f"[LayDraw] Máximo de apostas simultâneas atingido ({active_lay_draw}/{cfg['max_concurrent_bets']}).")
            return

        # Stake = 2% da banca disponível
        stake = round(balance * cfg['stake_pct'] / 100, 2)
        stake = max(stake, 2.0)  # mínimo Betfair

        logger.info(f"🎯 [LayDraw] Buscando oportunidades | banca R${balance:.2f} | stake R${stake:.2f} | ativos {active_lay_draw}/{cfg['max_concurrent_bets']}")

        markets = self.find_live_match_odds_markets()
        if not markets:
            return

        slots_available = cfg['max_concurrent_bets'] - active_lay_draw

        for market in markets:
            if slots_available <= 0:
                break

            entry = self.check_lay_draw_entry(market)
            if not entry:
                continue

            draw_odd = entry['draw_odd']
            liability = round(stake * (draw_odd - 1), 2)

            if balance < liability:
                logger.warning(f"[LayDraw] Saldo insuficiente para liability R${liability:.2f} (disponível R${balance:.2f})")
                continue

            logger.info(f"📥 [LayDraw] Entrando — {entry['event_name']} | LAY empate @ {draw_odd:.2f} | stake R${stake:.2f} | liability R${liability:.2f}")

            bet_id = self.place_lay_bet(
                market_id=entry['market_id'],
                selection_id=str(entry['draw_runner_id']),
                price=draw_odd,
                stake=stake,
            )

            if bet_id:
                active_bet = ActiveBet(
                    bet_id=bet_id,
                    market_id=entry['market_id'],
                    event_id=str(entry['event_id']),
                    sport=SportType.SOCCER,
                    strategy='Lay Draw',
                    side='LAY',
                    selection_id=str(entry['draw_runner_id']),
                    entry_price=draw_odd,
                    entry_time=datetime.now(),
                    stake=stake,
                    liability=liability,
                    # reutilizamos esses campos para armazenar os gatilhos de saída
                    take_profit_pct=cfg['take_profit_odd'],
                    stop_loss_pct=cfg['stop_loss_odd'],
                )
                self.active_bets[bet_id] = active_bet
                self.stats['total_bets'] += 1
                self.stats['soccer_bets'] += 1

                msg = (f"📥 [LayDraw] Entrada realizada!\n"
                       f"   Jogo: {entry['event_name']}\n"
                       f"   LAY Empate @ {draw_odd:.2f}\n"
                       f"   Stake: R${stake:.2f} | Liability: R${liability:.2f}\n"
                       f"   Minuto: {entry['match_time']} | Volume: R${entry['total_matched']:.0f}")
                if self.telegram:
                    self.telegram.send_message(msg)

                self.db.save_bet(
                    bet_id=bet_id,
                    market_id=entry['market_id'],
                    event_id=str(entry['event_id']),
                    sport='Soccer',
                    strategy='Lay Draw',
                    side='LAY',
                    selection_id=str(entry['draw_runner_id']),
                    entry_price=draw_odd,
                    stake=stake,
                    liability=liability,
                    event_name=entry['event_name'],
                )

                slots_available -= 1
                # Atualizar saldo estimado
                balance -= liability

    # =========================================================================

    def run(self):
        """Loop principal do bot"""
        logger.info("=" * 60)
        logger.info("🤖 Bot iniciado - Procurando oportunidades...")
        logger.info("=" * 60)
        
        while True:
            try:
                cycle_start = datetime.now()
                logger.info(f"\n🔄 Ciclo #{self.bet_counter + 1} - {cycle_start.strftime('%H:%M:%S')}")
                
                # Recarregar configurações do arquivo (permite alteração em tempo real)
                self.reload_config()
                
                # Verificar login — se token sumiu, tentar rede diretamente
                if not self.api.session_token:
                    logger.warning("⚠️ Sem token de sessão, solicitando novo via rede...")
                    if not self.api.login(force_fresh=True):
                        logger.error("❌ Falha no login. Aguardando 60s antes de tentar novamente...")
                        time.sleep(60)
                        continue
                    else:
                        logger.info("✅ Login realizado com sucesso")
                
                # Monitorar apostas ativas
                active_count = sum(1 for b in self.active_bets.values() if b.status == BetStatus.ACTIVE)
                if active_count > 0:
                    logger.info(f"📊 Monitorando {active_count} aposta(s) ativa(s)...")
                self.monitor_active_bets()
                self.monitor_lay_draw_bets()

                # Processar estratégias
                if self.soccer_config['enabled']:
                    self.process_soccer_strategy()
                    if self.soccer_config.get('entry_goal_line', 1.5) == 0.5:
                        self.process_under_high_hedge_monitoring()
                        self.process_zero_zero_protection()
                else:
                    logger.debug("Estratégia de futebol desabilitada no config")

                # Lay Draw
                if self.lay_draw_config['enabled']:
                    self.process_lay_draw_strategy()

                # Trading Pré-Jogo (Green Book) - roda em paralelo
                if self.pre_match_trading_config['enabled']:
                    self.process_pre_match_trading_strategy()
                
                # Hóquei desabilitado
                # if self.hockey_config['enabled']:
                #     self.process_hockey_strategy()
                
                if self.tennis_config['enabled']:
                    self.process_tennis_strategy()
                
                # Estatísticas a cada 10 ciclos
                if self.bet_counter % 10 == 0:
                    self.print_stats()
                    # Atualizar estatísticas diárias no banco
                    self.db.update_daily_stats()
                
                self.bet_counter += 1
                
                # Aguardar antes do próximo ciclo
                time.sleep(self.check_interval)
                
            except KeyboardInterrupt:
                logger.info("Bot interrompido pelo usuário")
                break
            except Exception as e:
                error_str = str(e)
                # Se for erro de sessão, tentar fazer novo login
                if 'INVALID_SESSION' in error_str or 'Token' in error_str:
                    logger.warning("Erro de sessão detectado, solicitando novo login via rede...")
                    self.api.session_token = None
                    try:
                        if self.api.login(force_fresh=True):
                            logger.info("✓ Novo login realizado com sucesso")
                        else:
                            logger.error("Falha ao fazer novo login")
                    except Exception as login_error:
                        logger.error(f"Erro ao tentar fazer novo login: {login_error}")
                
                logger.error(f"Erro no loop principal: {e}", exc_info=True)
                time.sleep(self.check_interval)


if __name__ == '__main__':
    bot = BetfairTradingBot()
    bot.run()

