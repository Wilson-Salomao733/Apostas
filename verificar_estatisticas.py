#!/usr/bin/env python3
"""
Script para verificar e corrigir estatísticas do banco de dados
"""

from database import BetDatabase
from datetime import datetime, timedelta

db = BetDatabase()

print("=" * 60)
print("📊 VERIFICAÇÃO DE ESTATÍSTICAS")
print("=" * 60)
print()

# 1. Verificar apostas fechadas
print("1️⃣  Apostas Fechadas:")
closed_bets = db.get_bets_by_status('CLOSED_PROFIT') + db.get_bets_by_status('CLOSED_LOSS')
print(f"   Total fechadas: {len(closed_bets)}")

profit_bets = [b for b in closed_bets if 'PROFIT' in b['status']]
loss_bets = [b for b in closed_bets if 'LOSS' in b['status']]

print(f"   ✅ Com lucro: {len(profit_bets)}")
print(f"   ❌ Com perda: {len(loss_bets)}")
print()

# 2. Verificar profit_loss
print("2️⃣  Verificando profit_loss:")
bets_with_profit = [b for b in closed_bets if b.get('profit_loss') is not None]
bets_without_profit = [b for b in closed_bets if b.get('profit_loss') is None]

print(f"   Com profit_loss: {len(bets_with_profit)}")
print(f"   Sem profit_loss: {len(bets_without_profit)}")
print()

if bets_without_profit:
    print("   ⚠️  Apostas sem profit_loss:")
    for bet in bets_without_profit[:5]:
        print(f"      - {bet['bet_id']}: {bet['status']} - {bet.get('close_reason', 'N/A')}")
    print()

# 3. Calcular lucro total manualmente
print("3️⃣  Cálculo de Lucro Total:")
total_profit = 0
for bet in bets_with_profit:
    profit_loss = bet.get('profit_loss', 0)
    stake = bet.get('stake', 0)
    if profit_loss and stake:
        profit = stake * (profit_loss / 100)
        total_profit += profit
        print(f"   {bet['bet_id'][:10]}...: {profit_loss:+.2f}% × R$ {stake:.2f} = R$ {profit:+.2f}")

print()
print(f"   💰 Lucro Total Calculado: R$ {total_profit:.2f}")
print()

# 4. Verificar estatísticas do banco
print("4️⃣  Estatísticas do Banco:")
stats = db.get_statistics()
print(f"   Total apostas: {stats['total_bets']}")
print(f"   Apostas ativas: {stats['active_bets']}")
print(f"   Apostas com lucro: {stats['profit_bets']}")
print(f"   Apostas com perda: {stats['loss_bets']}")
print(f"   Lucro total (banco): R$ {stats['total_profit']:.2f}")
print()

# 5. Comparar
if abs(total_profit - stats['total_profit']) > 0.01:
    print("   ⚠️  DIFERENÇA ENCONTRADA!")
    print(f"   Calculado manualmente: R$ {total_profit:.2f}")
    print(f"   Do banco: R$ {stats['total_profit']:.2f}")
    print(f"   Diferença: R$ {abs(total_profit - stats['total_profit']):.2f}")
else:
    print("   ✅ Cálculos estão corretos!")
print()

# 6. Apostas dos últimos 2 dias
print("5️⃣  Apostas dos Últimos 2 Dias:")
end_date = datetime.now()
start_date = end_date - timedelta(days=2)
recent_bets = db.get_bets_by_date_range(
    start_date.strftime('%Y-%m-%d'),
    end_date.strftime('%Y-%m-%d')
)
print(f"   Total: {len(recent_bets)}")
active_recent = [b for b in recent_bets if b['status'] == 'ACTIVE']
closed_recent = [b for b in recent_bets if b['status'] != 'ACTIVE']
print(f"   Ativas: {len(active_recent)}")
print(f"   Fechadas: {len(closed_recent)}")
print()

print("=" * 60)
