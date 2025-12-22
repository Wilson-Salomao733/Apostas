#!/usr/bin/env python3
"""
Módulo para enviar notificações via Telegram Bot
"""

import requests
import logging
from typing import Optional, Dict
from configparser import ConfigParser

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Classe para enviar notificações via Telegram"""
    
    def __init__(self, config_file='bot_config.ini'):
        """Inicializa o notificador do Telegram"""
        self.config = ConfigParser()
        self.config.read(config_file)
        
        # Buscar configurações do Telegram
        self.token = self.config.get('telegram', 'bot_token', fallback=None)
        chat_id_raw = self.config.get('telegram', 'chat_id', fallback=None)
        self.enabled = self.config.getboolean('telegram', 'enabled', fallback=False)
        
        # Converter chat_id para string (pode vir como int do config)
        if chat_id_raw:
            self.chat_id = str(chat_id_raw)
        else:
            self.chat_id = None
        
        if not self.token or not self.chat_id:
            logger.warning("Telegram não configurado. Token ou Chat ID não encontrado.")
            self.enabled = False
        else:
            logger.info(f"Telegram notifier inicializado. Chat ID: {self.chat_id}")
    
    def send_message(self, message: str, parse_mode: str = 'HTML') -> bool:
        """
        Envia uma mensagem para o Telegram
        
        Args:
            message: Texto da mensagem
            parse_mode: Modo de parse (HTML ou Markdown)
            
        Returns:
            bool: True se enviado com sucesso, False caso contrário
        """
        if not self.enabled:
            return False
        
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            
            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': parse_mode
            }
            
            response = requests.post(url, json=payload, timeout=10)
            
            if response.status_code == 200:
                logger.debug("Mensagem enviada com sucesso para o Telegram")
                return True
            else:
                logger.warning(f"Erro ao enviar mensagem para Telegram: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem para Telegram: {e}")
            return False
    
    def notify_new_bet(self, bet_info: Dict, balance: Optional[Dict] = None) -> bool:
        """
        Envia notificação de nova aposta
        
        Args:
            bet_info: Dicionário com informações da aposta
            balance: Dicionário com informações de saldo (opcional)
            
        Returns:
            bool: True se enviado com sucesso
        """
        if not self.enabled:
            return False
        
        # Filtrar apenas futebol por enquanto
        sport = bet_info.get('sport', '')
        if sport != 'SOCCER':
            logger.debug(f"Notificação ignorada - esporte: {sport} (apenas futebol é notificado)")
            return False
        
        try:
            # Formatar mensagem
            sport_emoji = {
                'SOCCER': '⚽',
                'ICE_HOCKEY': '🏒',
                'TENNIS': '🎾'
            }.get(sport, '🎯')
            
            sport_name = {
                'SOCCER': 'Futebol',
                'ICE_HOCKEY': 'Hóquei',
                'TENNIS': 'Tênis'
            }.get(sport, 'Desconhecido')
            
            side_emoji = '✅' if bet_info.get('side') == 'BACK' else '❌'
            side_name = 'BACK' if bet_info.get('side') == 'BACK' else 'LAY'
            
            # Extrair nome do jogo/time
            event_name = bet_info.get('event_name', 'N/A')
            
            message = f"""
<b>{sport_emoji} NOVA APOSTA - {sport_name}</b>

<b>⚽ Jogo/Time:</b> {event_name}
<b>📊 Tipo:</b> {side_emoji} {side_name} - {bet_info.get('strategy', 'N/A')}
<b>💰 Odd:</b> {bet_info.get('entry_price', 0):.2f}
<b>💵 Stake:</b> R$ {bet_info.get('stake', 0):.2f}
"""
            
            # Adicionar liability se for LAY
            if bet_info.get('side') == 'LAY' and bet_info.get('liability', 0) > 0:
                message += f"<b>⚠️ Liabilidade:</b> R$ {bet_info.get('liability', 0):.2f}\n"
            
            # Adicionar saldo se disponível
            if balance:
                message += f"""
<b>💰 Saldo Atual:</b>
  • Disponível: R$ {balance.get('available', 0):.2f}
  • Total: R$ {balance.get('total', 0):.2f}
"""
                if balance.get('exposure', 0) > 0:
                    message += f"  • Exposição: R$ {balance.get('exposure', 0):.2f}\n"
            
            message += f"\n<b>🆔 Bet ID:</b> <code>{bet_info.get('bet_id', 'N/A')[:12]}...</code>"
            
            return self.send_message(message)
            
        except Exception as e:
            logger.error(f"Erro ao enviar notificação de nova aposta: {e}")
            return False
    
    def notify_bet_closed(self, bet_info: Dict, result: str, profit_loss: float) -> bool:
        """
        Envia notificação de aposta fechada
        
        Args:
            bet_info: Dicionário com informações da aposta
            result: Resultado (PROFIT, LOSS, TIMEOUT)
            profit_loss: Lucro/prejuízo em percentual
            
        Returns:
            bool: True se enviado com sucesso
        """
        if not self.enabled:
            return False
        
        try:
            sport_emoji = {
                'SOCCER': '⚽',
                'ICE_HOCKEY': '🏒',
                'TENNIS': '🎾'
            }.get(bet_info.get('sport', ''), '🎯')
            
            if result == 'PROFIT':
                emoji = '✅'
                status = 'GANHOU'
            elif result == 'LOSS':
                emoji = '❌'
                status = 'PERDEU'
            else:
                emoji = '⏰'
                status = 'TIMEOUT'
            
            stake = bet_info.get('stake', 0)
            profit_value = stake * (profit_loss / 100)
            
            message = f"""
<b>{emoji} APOSTA FECHADA - {status}</b>

<b>Jogo:</b> {bet_info.get('event_name', 'N/A')}
<b>Resultado:</b> {emoji} {status}
<b>P&L:</b> {profit_loss:+.2f}% ({profit_value:+.2f} R$)
<b>Motivo:</b> {bet_info.get('close_reason', 'N/A')}
"""
            
            return self.send_message(message)
            
        except Exception as e:
            logger.error(f"Erro ao enviar notificação de aposta fechada: {e}")
            return False
