#!/usr/bin/env python3
"""
Módulo de Banco de Dados para o Bot Betfair
Gerencia apostas e resultados usando SQLite
"""

import sqlite3
import json
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class BetDatabase:
    """Gerencia o banco de dados de apostas"""
    
    def __init__(self, db_path: str = 'data/bets.db'):
        """Inicializa conexão com o banco de dados"""
        self.db_path = db_path
        
        # Criar diretório se não existir
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Criar tabelas se não existirem
        self._create_tables()
        logger.info(f"Banco de dados inicializado: {db_path}")
    
    def _get_connection(self, timeout: float = 10.0):
        """Obtém uma conexão com o banco de dados com timeout e WAL mode"""
        conn = sqlite3.connect(self.db_path, timeout=timeout)
        conn.row_factory = sqlite3.Row  # Para acessar colunas por nome
        
        # Habilitar WAL mode para permitir leituras concorrentes
        try:
            conn.execute('PRAGMA journal_mode=WAL')
        except Exception as e:
            logger.debug(f"Não foi possível habilitar WAL mode: {e}")
        
        return conn
    
    def _create_tables(self):
        """Cria as tabelas do banco de dados"""
        conn = self._get_connection(timeout=30.0)  # Timeout maior para criação de tabelas
        cursor = conn.cursor()
        
        # Tabela de apostas
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bets (
                bet_id TEXT PRIMARY KEY,
                market_id TEXT NOT NULL,
                event_id TEXT,
                event_name TEXT,
                sport TEXT NOT NULL,
                strategy TEXT NOT NULL,
                side TEXT NOT NULL,
                selection_id TEXT NOT NULL,
                entry_price REAL NOT NULL,
                entry_time TIMESTAMP NOT NULL,
                stake REAL NOT NULL,
                liability REAL DEFAULT 0,
                take_profit_pct REAL NOT NULL,
                stop_loss_pct REAL NOT NULL,
                status TEXT NOT NULL,
                current_price REAL,
                profit_loss REAL,
                close_reason TEXT,
                close_time TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tabela de estatísticas diárias
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE NOT NULL UNIQUE,
                total_bets INTEGER DEFAULT 0,
                profit_bets INTEGER DEFAULT 0,
                loss_bets INTEGER DEFAULT 0,
                total_profit REAL DEFAULT 0.0,
                soccer_bets INTEGER DEFAULT 0,
                hockey_bets INTEGER DEFAULT 0,
                tennis_bets INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tabela de saldo da conta (histórico)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS balance_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                available REAL NOT NULL,
                total REAL NOT NULL,
                exposure REAL DEFAULT 0
            )
        """)
        
        # Índices para melhorar performance
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_bets_status 
            ON bets(status)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_bets_sport 
            ON bets(sport)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_bets_entry_time 
            ON bets(entry_time)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_daily_stats_date 
            ON daily_stats(date)
        """)
        
        # Adicionar novos campos se não existirem (migração)
        self._add_new_columns_if_needed(cursor)
        
        conn.commit()
        conn.close()
        logger.info("Tabelas do banco de dados criadas/verificadas")
    
    def _add_new_columns_if_needed(self, cursor):
        """Adiciona novos campos à tabela bets se não existirem"""
        try:
            # Verificar quais colunas já existem
            cursor.execute("PRAGMA table_info(bets)")
            existing_columns = [row[1] for row in cursor.fetchall()]
            
            # Campos a adicionar
            new_columns = {
                'game_score': 'TEXT',
                'market_status': 'TEXT',
                'runner_status': 'TEXT',
                'gross_profit': 'REAL',
                'net_profit': 'REAL',
                'settled_date': 'TIMESTAMP'
            }
            
            for column_name, column_type in new_columns.items():
                if column_name not in existing_columns:
                    try:
                        cursor.execute(f"ALTER TABLE bets ADD COLUMN {column_name} {column_type}")
                        logger.info(f"Coluna {column_name} adicionada à tabela bets")
                    except sqlite3.OperationalError as e:
                        logger.warning(f"Erro ao adicionar coluna {column_name}: {e}")
        except Exception as e:
            logger.error(f"Erro ao verificar/adicionar colunas: {e}")
    
    def insert_bet(self, bet_data: Dict) -> bool:
        """Insere uma nova aposta no banco de dados com retry em caso de lock"""
        import time
        max_retries = 5
        retry_delay = 0.1  # 100ms
        
        for attempt in range(max_retries):
            try:
                conn = self._get_connection(timeout=5.0)
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT INTO bets (
                        bet_id, market_id, event_id, event_name, sport, strategy,
                        side, selection_id, entry_price, entry_time, stake, liability,
                        take_profit_pct, stop_loss_pct, status, current_price,
                        profit_loss, close_reason, close_time
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    bet_data['bet_id'],
                    bet_data['market_id'],
                    bet_data.get('event_id'),
                    bet_data.get('event_name'),
                    bet_data['sport'],
                    bet_data['strategy'],
                    bet_data['side'],
                    bet_data['selection_id'],
                    bet_data['entry_price'],
                    bet_data['entry_time'],
                    bet_data['stake'],
                    bet_data.get('liability', 0),
                    bet_data['take_profit_pct'],
                    bet_data['stop_loss_pct'],
                    bet_data['status'],
                    bet_data.get('current_price'),
                    bet_data.get('profit_loss'),
                    bet_data.get('close_reason'),
                    bet_data.get('close_time')
                ))
                
                conn.commit()
                conn.close()
                logger.info(f"Aposta inserida no banco: {bet_data['bet_id']}")
                return True
            except sqlite3.IntegrityError as e:
                conn.close()
                logger.warning(f"Aposta {bet_data['bet_id']} já existe no banco")
                return False
            except sqlite3.OperationalError as e:
                conn.close()
                error_msg = str(e).lower()
                if 'locked' in error_msg and attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                    logger.debug(f"Banco travado, tentando novamente em {wait_time:.2f}s (tentativa {attempt + 1}/{max_retries})...")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Erro ao inserir aposta no banco: {e}")
                    return False
            except Exception as e:
                if 'conn' in locals():
                    conn.close()
                logger.error(f"Erro ao inserir aposta no banco: {e}")
                return False
        
        return False
    
    def update_bet(self, bet_id: str, update_data: Dict) -> bool:
        """Atualiza uma aposta existente com retry em caso de lock"""
        import time
        max_retries = 5
        retry_delay = 0.1  # 100ms
        
        for attempt in range(max_retries):
            try:
                conn = self._get_connection(timeout=5.0)
                cursor = conn.cursor()
                
                # Construir query dinamicamente baseado nos campos a atualizar
                fields = []
                values = []
                for key, value in update_data.items():
                    fields.append(f"{key} = ?")
                    values.append(value)
                
                # Adicionar timestamp de atualização
                fields.append("updated_at = CURRENT_TIMESTAMP")
                values.append(bet_id)
                
                query = f"UPDATE bets SET {', '.join(fields)} WHERE bet_id = ?"
                cursor.execute(query, values)
                
                conn.commit()
                rows_affected = cursor.rowcount
                conn.close()
                
                if rows_affected > 0:
                    logger.debug(f"Aposta atualizada no banco: {bet_id}")
                    return True
                else:
                    logger.warning(f"Aposta {bet_id} não encontrada para atualizar")
                    return False
            except sqlite3.OperationalError as e:
                if 'conn' in locals():
                    conn.close()
                error_msg = str(e).lower()
                if 'locked' in error_msg and attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                    logger.debug(f"Banco travado ao atualizar, tentando novamente em {wait_time:.2f}s (tentativa {attempt + 1}/{max_retries})...")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Erro ao atualizar aposta no banco: {e}")
                    return False
            except Exception as e:
                if 'conn' in locals():
                    conn.close()
                logger.error(f"Erro ao atualizar aposta no banco: {e}")
                return False
        
        return False
    
    def get_bet(self, bet_id: str) -> Optional[Dict]:
        """Obtém uma aposta específica"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM bets WHERE bet_id = ?", (bet_id,))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return dict(row)
            return None
        except Exception as e:
            logger.error(f"Erro ao buscar aposta no banco: {e}")
            return None
    
    def get_active_bets(self) -> List[Dict]:
        """Obtém todas as apostas ativas das últimas 24 horas com retry em caso de lock"""
        import time
        max_retries = 3
        retry_delay = 0.1
        
        for attempt in range(max_retries):
            try:
                conn = self._get_connection(timeout=5.0)
                cursor = conn.cursor()
                
                # Buscar apenas apostas ativas das últimas 24 horas
                from datetime import datetime, timedelta
                agora = datetime.now()
                vinte_quatro_horas_atras = agora - timedelta(hours=24)
                vinte_quatro_horas_atras_str = vinte_quatro_horas_atras.strftime('%Y-%m-%d %H:%M:%S')
                
                cursor.execute("""
                    SELECT * FROM bets 
                    WHERE status = 'ACTIVE' 
                    AND entry_time >= ?
                    ORDER BY entry_time DESC
                """, (vinte_quatro_horas_atras_str,))
                
                rows = cursor.fetchall()
                conn.close()
                
                bets = [dict(row) for row in rows]
                logger.debug(f"Encontradas {len(bets)} apostas ativas das últimas 24 horas")
                return bets
            except sqlite3.OperationalError as e:
                if 'conn' in locals():
                    conn.close()
                error_msg = str(e).lower()
                if 'locked' in error_msg and attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    logger.debug(f"Banco travado ao buscar apostas ativas, tentando novamente em {wait_time:.2f}s...")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Erro ao buscar apostas ativas: {e}")
                    return []
            except Exception as e:
                if 'conn' in locals():
                    conn.close()
                logger.error(f"Erro ao buscar apostas ativas: {e}")
                return []
        
        return []
    
    def get_bets_by_status(self, status: str) -> List[Dict]:
        """Obtém apostas por status"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM bets 
                WHERE status = ? 
                ORDER BY entry_time DESC
            """, (status,))
            
            rows = cursor.fetchall()
            conn.close()
            
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Erro ao buscar apostas por status: {e}")
            return []
    
    def get_bets_by_date_range(self, start_date: str, end_date: str) -> List[Dict]:
        """Obtém apostas em um intervalo de datas"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM bets 
                WHERE DATE(entry_time) BETWEEN ? AND ?
                ORDER BY entry_time DESC
            """, (start_date, end_date))
            
            rows = cursor.fetchall()
            conn.close()
            
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Erro ao buscar apostas por data: {e}")
            return []
    
    def get_today_bets(self) -> List[Dict]:
        """Obtém apostas de hoje"""
        today = datetime.now().strftime('%Y-%m-%d')
        return self.get_bets_by_date_range(today, today)
    
    def get_statistics(self) -> Dict:
        """Obtém estatísticas gerais"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Total de apostas
            cursor.execute("SELECT COUNT(*) as total FROM bets")
            total_bets = cursor.fetchone()['total']
            
            # Apostas ativas
            cursor.execute("SELECT COUNT(*) as active FROM bets WHERE status = 'ACTIVE'")
            active_bets = cursor.fetchone()['active']
            
            # Apostas com lucro
            cursor.execute("""
                SELECT COUNT(*) as profit FROM bets 
                WHERE status IN ('CLOSED_PROFIT', 'closed_profit')
            """)
            profit_bets = cursor.fetchone()['profit']
            
            # Apostas com perda
            cursor.execute("""
                SELECT COUNT(*) as loss FROM bets 
                WHERE status IN ('CLOSED_LOSS', 'closed_loss')
            """)
            loss_bets = cursor.fetchone()['loss']
            
            # Lucro total - calcular corretamente
            # profit_loss já está em porcentagem, então: lucro = stake * (profit_loss / 100)
            cursor.execute("""
                SELECT COALESCE(SUM(
                    CASE 
                        WHEN profit_loss IS NOT NULL AND profit_loss != 0 
                        THEN stake * (profit_loss / 100.0)
                        ELSE 0
                    END
                ), 0) as total_profit 
                FROM bets 
                WHERE (status LIKE 'CLOSED%' OR status LIKE 'closed%')
                AND profit_loss IS NOT NULL
            """)
            total_profit = cursor.fetchone()['total_profit']
            
            # Apostas por esporte
            cursor.execute("""
                SELECT 
                    SUM(CASE WHEN sport LIKE '%SOCCER%' THEN 1 ELSE 0 END) as soccer,
                    SUM(CASE WHEN sport LIKE '%HOCKEY%' THEN 1 ELSE 0 END) as hockey,
                    SUM(CASE WHEN sport LIKE '%TENNIS%' THEN 1 ELSE 0 END) as tennis
                FROM bets
            """)
            sports = cursor.fetchone()
            
            conn.close()
            
            return {
                'total_bets': total_bets,
                'active_bets': active_bets,
                'profit_bets': profit_bets,
                'loss_bets': loss_bets,
                'total_profit': float(total_profit) if total_profit else 0.0,
                'soccer_bets': sports['soccer'] or 0,
                'hockey_bets': sports['hockey'] or 0,
                'tennis_bets': sports['tennis'] or 0,
            }
        except Exception as e:
            logger.error(f"Erro ao buscar estatísticas: {e}")
            return {
                'total_bets': 0,
                'active_bets': 0,
                'profit_bets': 0,
                'loss_bets': 0,
                'total_profit': 0.0,
                'soccer_bets': 0,
                'hockey_bets': 0,
                'tennis_bets': 0,
            }
    
    def save_balance(self, available: float, total: float, exposure: float = 0) -> bool:
        """Salva snapshot do saldo da conta"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO balance_history (available, total, exposure)
                VALUES (?, ?, ?)
            """, (available, total, exposure))
            
            conn.commit()
            conn.close()
            logger.debug(f"Saldo salvo: disponível={available:.2f}, total={total:.2f}")
            return True
        except Exception as e:
            logger.error(f"Erro ao salvar saldo: {e}")
            return False
    
    def get_latest_balance(self) -> Optional[Dict]:
        """Obtém o último saldo registrado"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM balance_history 
                ORDER BY timestamp DESC 
                LIMIT 1
            """)
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return dict(row)
            return None
        except Exception as e:
            logger.error(f"Erro ao buscar último saldo: {e}")
            return None
    
    def update_daily_stats(self, date: str = None) -> bool:
        """Atualiza estatísticas diárias"""
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Calcular estatísticas do dia
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_bets,
                    SUM(CASE WHEN status IN ('CLOSED_PROFIT', 'closed_profit') THEN 1 ELSE 0 END) as profit_bets,
                    SUM(CASE WHEN status IN ('CLOSED_LOSS', 'closed_loss') THEN 1 ELSE 0 END) as loss_bets,
                    COALESCE(SUM(CASE WHEN status LIKE 'CLOSED%' OR status LIKE 'closed%' 
                                      THEN profit_loss * stake / 100 ELSE 0 END), 0) as total_profit,
                    SUM(CASE WHEN sport LIKE '%SOCCER%' THEN 1 ELSE 0 END) as soccer_bets,
                    SUM(CASE WHEN sport LIKE '%HOCKEY%' THEN 1 ELSE 0 END) as hockey_bets,
                    SUM(CASE WHEN sport LIKE '%TENNIS%' THEN 1 ELSE 0 END) as tennis_bets
                FROM bets
                WHERE DATE(entry_time) = ?
            """, (date,))
            
            stats = cursor.fetchone()
            
            # Inserir ou atualizar
            cursor.execute("""
                INSERT INTO daily_stats (
                    date, total_bets, profit_bets, loss_bets, total_profit,
                    soccer_bets, hockey_bets, tennis_bets
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    total_bets = excluded.total_bets,
                    profit_bets = excluded.profit_bets,
                    loss_bets = excluded.loss_bets,
                    total_profit = excluded.total_profit,
                    soccer_bets = excluded.soccer_bets,
                    hockey_bets = excluded.hockey_bets,
                    tennis_bets = excluded.tennis_bets,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                date,
                stats['total_bets'],
                stats['profit_bets'],
                stats['loss_bets'],
                stats['total_profit'],
                stats['soccer_bets'],
                stats['hockey_bets'],
                stats['tennis_bets']
            ))
            
            conn.commit()
            conn.close()
            logger.debug(f"Estatísticas diárias atualizadas para {date}")
            return True
        except Exception as e:
            logger.error(f"Erro ao atualizar estatísticas diárias: {e}")
            return False
    
    def get_daily_stats(self, days: int = 30) -> List[Dict]:
        """Obtém estatísticas dos últimos N dias"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM daily_stats 
                ORDER BY date DESC 
                LIMIT ?
            """, (days,))
            
            rows = cursor.fetchall()
            conn.close()
            
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Erro ao buscar estatísticas diárias: {e}")
            return []
    
    def close_bet(self, bet_id: str, status: str, profit_loss: float, 
                  close_reason: str, current_price: float) -> bool:
        """Fecha uma aposta e atualiza estatísticas"""
        close_time = datetime.now().isoformat()
        
        success = self.update_bet(bet_id, {
            'status': status,
            'profit_loss': profit_loss,
            'close_reason': close_reason,
            'current_price': current_price,
            'close_time': close_time
        })
        
        if success:
            # Atualizar estatísticas do dia
            self.update_daily_stats()
        
        return success
    
    def update_bet_settled_data(self, bet_id: str, settled_data: Dict) -> bool:
        """Atualiza uma aposta com dados da API de atividade (settled bets)"""
        try:
            update_fields = {}
            
            if 'grossProfit' in settled_data:
                update_fields['gross_profit'] = float(settled_data['grossProfit']) if settled_data['grossProfit'] else None
            if 'netProfit' in settled_data:
                update_fields['net_profit'] = float(settled_data['netProfit']) if settled_data['netProfit'] else None
            
            # Se tem lucro/prejuízo, atualizar status e profit_loss
            if 'grossProfit' in settled_data and settled_data['grossProfit']:
                gross_profit = float(settled_data['grossProfit'])
                if gross_profit > 0:
                    update_fields['status'] = 'CLOSED_PROFIT'
                elif gross_profit < 0:
                    update_fields['status'] = 'CLOSED_LOSS'
                
                # Calcular profit_loss percentual se tiver stake
                bet = self.get_bet(bet_id)
                if bet and bet.get('stake'):
                    profit_loss_pct = (gross_profit / bet['stake']) * 100
                    update_fields['profit_loss'] = profit_loss_pct
            
            if 'settledDate' in settled_data:
                update_fields['settled_date'] = settled_data['settledDate']
            
            if update_fields:
                return self.update_bet(bet_id, update_fields)
            
            return False
        except Exception as e:
            logger.error(f"Erro ao atualizar dados de aposta finalizada: {e}")
            return False
    
    def update_bet_game_info(self, bet_id: str, game_score: str = None, 
                             market_status: str = None, runner_status: str = None) -> bool:
        """Atualiza informações do jogo (placar, status) de uma aposta"""
        try:
            update_fields = {}
            if game_score:
                update_fields['game_score'] = game_score
            if market_status:
                update_fields['market_status'] = market_status
            if runner_status:
                update_fields['runner_status'] = runner_status
            
            if update_fields:
                return self.update_bet(bet_id, update_fields)
            
            return False
        except Exception as e:
            logger.error(f"Erro ao atualizar informações do jogo: {e}")
            return False
