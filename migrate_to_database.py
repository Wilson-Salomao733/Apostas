#!/usr/bin/env python3
"""
Script de migração de dados JSON para banco de dados SQLite
Converte apostas do arquivo logs/active_bets.json para o banco
"""

import json
import os
from pathlib import Path
from datetime import datetime
from database import BetDatabase

def migrate_json_to_db():
    """Migra dados do arquivo JSON para o banco de dados"""
    
    # Inicializar banco
    db = BetDatabase()
    
    # Caminho do arquivo JSON antigo
    json_file = 'logs/active_bets.json'
    
    if not os.path.exists(json_file):
        print(f"❌ Arquivo {json_file} não encontrado")
        print("   Nenhuma migração necessária")
        return
    
    print(f"🔄 Iniciando migração de {json_file} para o banco de dados...")
    
    try:
        # Ler arquivo JSON
        with open(json_file, 'r') as f:
            bets_json = json.load(f)
        
        print(f"📄 Encontradas {len(bets_json)} apostas no arquivo JSON")
        
        migrated = 0
        skipped = 0
        errors = 0
        
        for bet_id, bet_data in bets_json.items():
            try:
                # Preparar dados para o banco
                db_data = {
                    'bet_id': bet_id,
                    'market_id': bet_data.get('market_id', ''),
                    'event_id': bet_data.get('event_id', ''),
                    'event_name': '',  # JSON antigo não tinha, deixar vazio
                    'sport': bet_data.get('sport', 'SOCCER'),
                    'strategy': bet_data.get('strategy', ''),
                    'side': bet_data.get('side', 'BACK'),
                    'selection_id': str(bet_data.get('selection_id', '')),
                    'entry_price': float(bet_data.get('entry_price', 0)),
                    'entry_time': bet_data.get('entry_time', datetime.now().isoformat()),
                    'stake': float(bet_data.get('stake', 0)),
                    'liability': float(bet_data.get('liability', 0)),
                    'take_profit_pct': float(bet_data.get('take_profit_pct', 0)),
                    'stop_loss_pct': float(bet_data.get('stop_loss_pct', 0)),
                    'status': bet_data.get('status', 'ACTIVE'),
                    'current_price': float(bet_data['current_price']) if bet_data.get('current_price') else None,
                    'profit_loss': float(bet_data['profit_loss']) if bet_data.get('profit_loss') else None,
                    'close_reason': bet_data.get('close_reason'),
                    'close_time': None,  # JSON antigo não tinha
                }
                
                # Tentar inserir no banco
                if db.insert_bet(db_data):
                    migrated += 1
                    print(f"  ✓ Migrada: {bet_id}")
                else:
                    skipped += 1
                    print(f"  ⚠ Já existe: {bet_id}")
            
            except Exception as e:
                errors += 1
                print(f"  ❌ Erro ao migrar {bet_id}: {e}")
        
        print("\n" + "=" * 60)
        print("📊 RESULTADO DA MIGRAÇÃO:")
        print("=" * 60)
        print(f"  ✓ Migradas com sucesso: {migrated}")
        print(f"  ⚠ Ignoradas (já existem): {skipped}")
        print(f"  ❌ Erros: {errors}")
        print(f"  📄 Total no arquivo: {len(bets_json)}")
        print("=" * 60)
        
        if migrated > 0:
            # Atualizar estatísticas
            db.update_daily_stats()
            print("\n✓ Estatísticas atualizadas no banco")
        
        # Criar backup do arquivo JSON
        if migrated > 0 or skipped > 0:
            backup_file = f"{json_file}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            import shutil
            shutil.copy2(json_file, backup_file)
            print(f"💾 Backup criado: {backup_file}")
        
        print("\n✅ Migração concluída!")
        
    except Exception as e:
        print(f"\n❌ Erro durante a migração: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    print("=" * 60)
    print("🔄 MIGRAÇÃO DE DADOS JSON → BANCO DE DADOS")
    print("=" * 60)
    print()
    
    migrate_json_to_db()
