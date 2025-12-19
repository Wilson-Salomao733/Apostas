#!/usr/bin/env python3
"""
Utilitário para visualizar dados do banco de dados
"""

from database import BetDatabase
from datetime import datetime, timedelta
import sys

def print_separator():
    print("=" * 80)

def print_statistics():
    """Mostra estatísticas gerais"""
    db = BetDatabase()
    stats = db.get_statistics()
    
    print_separator()
    print("📊 ESTATÍSTICAS GERAIS")
    print_separator()
    print(f"Total de apostas:        {stats['total_bets']}")
    print(f"Apostas ativas:          {stats['active_bets']}")
    print(f"Apostas com lucro:       {stats['profit_bets']}")
    print(f"Apostas com perda:       {stats['loss_bets']}")
    print(f"Lucro total:             R$ {stats['total_profit']:.2f}")
    print()
    print(f"Por esporte:")
    print(f"  ⚽ Futebol:             {stats['soccer_bets']}")
    print(f"  🏒 Hóquei:              {stats['hockey_bets']}")
    print(f"  🎾 Tênis:               {stats['tennis_bets']}")
    print_separator()

def print_active_bets():
    """Mostra apostas ativas"""
    db = BetDatabase()
    bets = db.get_active_bets()
    
    print_separator()
    print(f"🔴 APOSTAS ATIVAS ({len(bets)})")
    print_separator()
    
    if not bets:
        print("Nenhuma aposta ativa no momento")
    else:
        for bet in bets:
            print(f"\nBet ID: {bet['bet_id']}")
            print(f"  Evento:       {bet['event_name'] or 'N/A'}")
            print(f"  Esporte:      {bet['sport']}")
            print(f"  Estratégia:   {bet['strategy']}")
            print(f"  Lado:         {bet['side']}")
            print(f"  Odd entrada:  {bet['entry_price']:.2f}")
            print(f"  Stake:        R$ {bet['stake']:.2f}")
            print(f"  Entrada:      {bet['entry_time']}")
            if bet['current_price']:
                print(f"  Odd atual:    {bet['current_price']:.2f}")
            if bet['profit_loss']:
                profit_color = '🟢' if bet['profit_loss'] > 0 else '🔴'
                print(f"  P&L:          {profit_color} {bet['profit_loss']:.2f}%")
    
    print_separator()

def print_today_bets():
    """Mostra apostas de hoje"""
    db = BetDatabase()
    bets = db.get_today_bets()
    
    print_separator()
    print(f"📅 APOSTAS DE HOJE ({len(bets)})")
    print_separator()
    
    if not bets:
        print("Nenhuma aposta feita hoje")
    else:
        active = [b for b in bets if b['status'] == 'ACTIVE']
        closed_profit = [b for b in bets if 'PROFIT' in b['status']]
        closed_loss = [b for b in bets if 'LOSS' in b['status']]
        
        print(f"\n✅ Ativas:         {len(active)}")
        print(f"🟢 Com lucro:      {len(closed_profit)}")
        print(f"🔴 Com perda:      {len(closed_loss)}")
        
        total_profit = sum(
            (b['profit_loss'] * b['stake'] / 100) 
            for b in bets 
            if b['profit_loss'] and 'CLOSED' in b['status']
        )
        print(f"\n💰 Lucro do dia:   R$ {total_profit:.2f}")
        
        print("\nDetalhes:")
        for bet in bets:
            status_icon = {
                'ACTIVE': '⏳',
                'CLOSED_PROFIT': '✅',
                'CLOSED_LOSS': '❌',
                'CLOSED_TIMEOUT': '⏰'
            }.get(bet['status'], '❓')
            
            profit_str = f"{bet['profit_loss']:+.2f}%" if bet['profit_loss'] else "N/A"
            print(f"\n  {status_icon} {bet['bet_id'][:10]}... | {bet['sport']:10} | {bet['side']:4} | "
                  f"Odd: {bet['entry_price']:6.2f} | P&L: {profit_str:8}")
    
    print_separator()

def print_recent_history(days=7):
    """Mostra histórico recente"""
    db = BetDatabase()
    stats = db.get_daily_stats(days)
    
    print_separator()
    print(f"📈 HISTÓRICO DOS ÚLTIMOS {days} DIAS")
    print_separator()
    
    if not stats:
        print("Nenhum dado histórico disponível")
    else:
        print(f"\n{'Data':<12} {'Total':<7} {'Lucros':<8} {'Perdas':<8} {'Lucro R$':<12}")
        print("-" * 60)
        
        for stat in reversed(stats):  # Mostrar do mais antigo para o mais recente
            date = stat['date']
            total = stat['total_bets']
            profits = stat['profit_bets']
            losses = stat['loss_bets']
            profit = stat['total_profit']
            
            profit_color = '🟢' if profit > 0 else '🔴' if profit < 0 else '⚪'
            print(f"{date:<12} {total:<7} {profits:<8} {losses:<8} {profit_color} R$ {profit:>8.2f}")
        
        # Totais
        total_bets = sum(s['total_bets'] for s in stats)
        total_profits = sum(s['profit_bets'] for s in stats)
        total_losses = sum(s['loss_bets'] for s in stats)
        total_profit = sum(s['total_profit'] for s in stats)
        
        print("-" * 60)
        print(f"{'TOTAL':<12} {total_bets:<7} {total_profits:<8} {total_losses:<8} 💰 R$ {total_profit:>8.2f}")
    
    print_separator()

def print_balance():
    """Mostra saldo atual"""
    db = BetDatabase()
    balance = db.get_latest_balance()
    
    print_separator()
    print("💰 SALDO DA CONTA")
    print_separator()
    
    if balance:
        print(f"Disponível:  R$ {balance['available']:.2f}")
        print(f"Total:       R$ {balance['total']:.2f}")
        print(f"Exposição:   R$ {balance['exposure']:.2f}")
        print(f"Última atualização: {balance['timestamp']}")
    else:
        print("Nenhum dado de saldo disponível")
    
    print_separator()

def print_menu():
    """Mostra menu de opções"""
    print("\n" + "=" * 80)
    print("💾 VISUALIZADOR DO BANCO DE DADOS - BOT BETFAIR")
    print("=" * 80)
    print("\nOpções:")
    print("  1 - Ver estatísticas gerais")
    print("  2 - Ver apostas ativas")
    print("  3 - Ver apostas de hoje")
    print("  4 - Ver histórico (7 dias)")
    print("  5 - Ver histórico (30 dias)")
    print("  6 - Ver saldo da conta")
    print("  7 - Ver tudo")
    print("  0 - Sair")
    print()

def main():
    """Função principal"""
    
    if len(sys.argv) > 1:
        option = sys.argv[1]
    else:
        while True:
            print_menu()
            option = input("Escolha uma opção: ").strip()
            
            if option == '0':
                print("\n👋 Até logo!")
                break
            elif option == '1':
                print_statistics()
            elif option == '2':
                print_active_bets()
            elif option == '3':
                print_today_bets()
            elif option == '4':
                print_recent_history(7)
            elif option == '5':
                print_recent_history(30)
            elif option == '6':
                print_balance()
            elif option == '7':
                print_statistics()
                print_balance()
                print_active_bets()
                print_today_bets()
                print_recent_history(7)
            else:
                print("\n❌ Opção inválida!")
            
            input("\nPressione ENTER para continuar...")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Até logo!")
    except Exception as e:
        print(f"\n❌ Erro: {e}")
        import traceback
        traceback.print_exc()
