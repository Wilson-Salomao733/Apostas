#!/usr/bin/env python3
"""
Módulo para enviar notificações via Telegram Bot
Inclui polling de comandos para troca de estratégia.
"""

import json
import os
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

    # ─── Polling de Comandos ──────────────────────────────────────────────────

    STRATEGY_FILE = "data/active_strategy.txt"
    OFFSET_FILE   = "data/telegram_offset.txt"

    STRATEGIES = {
        # Aceita variações com/sem acento, número ou texto
        "estratégia 1": "over15",
        "estrategia 1": "over15",
        "estratégia1":  "over15",
        "estrategia1":  "over15",
        "/estrategia1": "over15",
        "/e1":          "over15",
        "over15":       "over15",
        "over 1.5":     "over15",
        "estratégia 2": "favorite",
        "estrategia 2": "favorite",
        "estratégia2":  "favorite",
        "estrategia2":  "favorite",
        "/estrategia2": "favorite",
        "/e2":          "favorite",
        "favorito":     "favorite",
        "favorite":     "favorite",
        # Under Máximo
        "estratégia 3": "under_max",
        "estrategia 3": "under_max",
        "estratégia3":  "under_max",
        "estrategia3":  "under_max",
        "/estrategia3": "under_max",
        "/e3":          "under_max",
        "under":        "under_max",
        "under max":    "under_max",
        "under_max":    "under_max",
        # Under 4.5 Fixo
        "estratégia 4": "under45",
        "estrategia 4": "under45",
        "estratégia4":  "under45",
        "estrategia4":  "under45",
        "/estrategia4": "under45",
        "/e4":          "under45",
        "under45":      "under45",
        "under 4.5":    "under45",
    }

    STRATEGY_LABELS = {
        "over15":    "Estratégia 1 — Over 1.5 Gols",
        "favorite":  "Estratégia 2 — Favorito (Match Odds)",
        "under_max": "Estratégia 3 — Under Máximo",
        "under45":   "Estratégia 4 — Under 4.5 Fixo",
        "over25":    "Estratégia Over 2.5 Gols",
    }

    def check_commands(self) -> Optional[str]:
        """
        Verifica se chegou algum comando de troca de estratégia no Telegram.
        Retorna o nome da nova estratégia ('over15', 'favorite') ou None.
        Também responde /status com o estado atual do bot.
        """
        if not self.enabled:
            return None

        updates = self._get_updates()
        new_strategy = None

        for update in updates:
            msg  = update.get("message", {})
            text = msg.get("text", "").lower().strip()

            if text in ("/status", "status", "/estado"):
                current = self._read_active_strategy()
                label   = self.STRATEGY_LABELS.get(current, current)
                self.send_message(
                    f"🤖 <b>Status do Bot</b>\n\n"
                    f"📊 Estratégia ativa: <b>{label}</b>\n\n"
                    f"Comandos:\n"
                    f"• <code>estratégia 1</code> → Over 1.5 Gols\n"
                    f"• <code>estratégia 2</code> → Favorito\n"
                    f"• <code>status</code> → Este menu"
                )
                continue

            mapped = self.STRATEGIES.get(text)
            if mapped:
                new_strategy = mapped
                label = self.STRATEGY_LABELS.get(mapped, mapped)
                self.send_message(
                    f"🔄 <b>Trocando estratégia...</b>\n\n"
                    f"✅ Nova estratégia: <b>{label}</b>\n"
                    f"⏳ O bot vai aplicar a mudança no próximo ciclo."
                )

        if new_strategy:
            self._write_active_strategy(new_strategy)

        return new_strategy

    def _get_updates(self) -> list:
        """Busca novas mensagens do Telegram (sem bloquear)."""
        try:
            offset = self._load_offset()
            resp = requests.get(
                f"https://api.telegram.org/bot{self.token}/getUpdates",
                params={"timeout": 0, "offset": offset},
                timeout=10,
                proxies={"http": None, "https": None},
            )
            if resp.status_code != 200:
                return []
            updates = resp.json().get("result", [])
            if updates:
                self._save_offset(updates[-1]["update_id"] + 1)
            return updates
        except Exception as e:
            logger.debug(f"Telegram getUpdates: {e}")
            return []

    def _load_offset(self) -> int:
        try:
            if os.path.exists(self.OFFSET_FILE):
                with open(self.OFFSET_FILE) as f:
                    return int(f.read().strip())
        except Exception:
            pass
        return 0

    def _save_offset(self, offset: int):
        os.makedirs("data", exist_ok=True)
        with open(self.OFFSET_FILE, "w") as f:
            f.write(str(offset))

    @staticmethod
    def _read_active_strategy() -> str:
        try:
            if os.path.exists(TelegramNotifier.STRATEGY_FILE):
                with open(TelegramNotifier.STRATEGY_FILE) as f:
                    return f.read().strip()
        except Exception:
            pass
        return "over15"

    @staticmethod
    def _write_active_strategy(strategy: str):
        os.makedirs("data", exist_ok=True)
        with open(TelegramNotifier.STRATEGY_FILE, "w") as f:
            f.write(strategy)
