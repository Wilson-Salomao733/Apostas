#!/usr/bin/env python3
"""
Script para limpar apostas antigas do banco de dados
Remove apostas com mais de 2 dias (mantém apenas últimos 2 dias)
"""

import sys
from datetime import datetime, timedelta
from database import BetDatabase
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def limpar_apostas_antigas():
    """Remove apostas com mais de 2 dias"""
    db = BetDatabase()
    
    # Data de corte: 2 dias atrás
    cutoff_date = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
    
    print("=" * 60)
    print("🧹 LIMPEZA DE APOSTAS ANTIGAS")
    print("=" * 60)
    print(f"\n📅 Mantendo apenas apostas de: {cutoff_date} em diante")
    print(f"🗑️  Removendo apostas anteriores a: {cutoff_date}")
    print()
    
    try:
        conn = db._get_connection()
        cursor = conn.cursor()
        
        # Contar apostas que serão removidas
        cursor.execute("""
            SELECT COUNT(*) as total
            FROM bets
            WHERE DATE(entry_time) < ?
        """, (cutoff_date,))
        
        count_to_delete = cursor.fetchone()['total']
        
        if count_to_delete == 0:
            print("✅ Nenhuma aposta antiga encontrada!")
            conn.close()
            return
        
        print(f"📊 Apostas que serão removidas: {count_to_delete}")
        print()
        
        # Confirmar
        resposta = input("Deseja continuar? (s/n): ").strip().lower()
        if resposta != 's':
            print("❌ Operação cancelada")
            conn.close()
            return
        
        # Remover apostas antigas
        cursor.execute("""
            DELETE FROM bets
            WHERE DATE(entry_time) < ?
        """, (cutoff_date,))
        
        rows_deleted = cursor.rowcount
        conn.commit()
        conn.close()
        
        print()
        print("=" * 60)
        print(f"✅ LIMPEZA CONCLUÍDA!")
        print("=" * 60)
        print(f"🗑️  Apostas removidas: {rows_deleted}")
        print(f"📅 Mantidas: Apostas de {cutoff_date} em diante")
        print()
        print("💡 Dica: Execute este script periodicamente para manter o banco limpo")
        print()
        
    except Exception as e:
        logger.error(f"Erro ao limpar apostas antigas: {e}")
        print(f"\n❌ Erro: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    limpar_apostas_antigas()
