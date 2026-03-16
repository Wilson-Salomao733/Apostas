# 🔧 Correção: Verificação de Odd Máxima

## Problema Identificado
O bot estava permitindo apostas com odds acima da configuração máxima (ex: odd 11 quando max_odd = 1.5).

## Correções Aplicadas

### 1. Adicionado `max_odd` no `soccer_config`
- Agora o bot lê `max_odd` do arquivo `bot_config.ini`
- Se o valor estiver vazio, trata como `None` (sem limite)

### 2. Adicionada verificação de odd máxima
- Verificação adicionada na função `check_soccer_entry_conditions`
- Rejeita apostas com odd acima do limite configurado
- Log de aviso quando rejeita por odd alta

### 3. Atualizada função `reload_config`
- Agora também atualiza `max_odd` quando a configuração é recarregada
- Log quando `max_odd` é alterado

## Código Adicionado

```python
# ✅ VERIFICAR ODD MÁXIMA: apenas apostar se odd <= max_odd configurado (se configurado)
max_odd = self.soccer_config.get('max_odd')
if max_odd is not None:
    try:
        max_odd_float = float(max_odd)
        if current_price > max_odd_float:
            logger.warning(f"🚫 Mercado {market_id}: Odd muito alta ({current_price:.2f} > {max_odd_float:.2f}) - REJEITANDO aposta (max_odd configurado)")
            return None
    except (ValueError, TypeError) as e:
        logger.warning(f"⚠️ Mercado {market_id}: Erro ao verificar max_odd ({max_odd}): {e}")
```

## ⚠️ IMPORTANTE: Reiniciar o Bot

**O bot precisa ser REINICIADO para carregar a nova configuração!**

1. Pare o bot
2. Inicie novamente
3. A verificação de odd máxima agora funcionará corretamente

## Como Verificar se Está Funcionando

1. Configure `max_odd = 1.5` no dashboard
2. Salve as configurações
3. **Reinicie o bot** (importante!)
4. Verifique os logs - você verá mensagens como:
   - `🚫 Mercado XXX: Odd muito alta (11.00 > 1.50) - REJEITANDO aposta`

## Teste

Para testar se está funcionando:
1. Configure `max_odd = 1.5`
2. Reinicie o bot
3. Monitore os logs - apostas com odd > 1.5 devem ser rejeitadas

