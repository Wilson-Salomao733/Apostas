# ⚠️ Aviso de Segurança - Docker Socket

## Configuração Atual

O dashboard agora monta o socket Docker (`/var/run/docker.sock`) por padrão para permitir que os botões de controle funcionem.

## 🔒 Considerações de Segurança

### O que isso permite:
- ✅ Controlar containers Docker via dashboard web
- ✅ Iniciar/parar/reiniciar containers
- ✅ Ver status de containers

### Riscos potenciais:
- ⚠️ Acesso total ao Docker daemon
- ⚠️ Possibilidade de criar/remover containers
- ⚠️ Acesso a todos os volumes e networks
- ⚠️ Em ambientes compartilhados, pode ser risco de segurança

## 🛡️ Recomendações

### Ambiente de Desenvolvimento (OK)
- ✅ Uso pessoal/local
- ✅ Máquina dedicada
- ✅ Acesso restrito ao servidor

### Ambiente de Produção (Cuidado)
- ⚠️ Considere remover o socket Docker
- ⚠️ Use autenticação adicional
- ⚠️ Limite acesso ao dashboard
- ⚠️ Use firewall/iptables

## 🔧 Como Remover (se necessário)

Se quiser remover o acesso ao Docker socket:

1. Edite `docker-compose-completo.yml` ou `docker-compose.dashboard-api.yml`
2. Remova ou comente a linha:
   ```yaml
   # - /var/run/docker.sock:/var/run/docker.sock:ro
   ```
3. Rebuild:
   ```bash
   docker compose -f docker-compose-completo.yml down
   docker compose -f docker-compose-completo.yml build dashboard-api
   docker compose -f docker-compose-completo.yml up -d
   ```

## ✅ Alternativa Segura

Se remover o socket Docker, use comandos manuais:

```bash
# Iniciar bot
docker compose -f docker-compose-completo.yml start betfair-bot

# Parar bot
docker compose -f docker-compose-completo.yml stop betfair-bot

# Reiniciar bot
docker compose -f docker-compose-completo.yml restart betfair-bot
```

## 📝 Nota

A configuração atual é adequada para:
- ✅ Desenvolvimento local
- ✅ Uso pessoal
- ✅ Ambientes controlados

Não recomendado para:
- ❌ Servidores públicos sem autenticação
- ❌ Ambientes multi-usuário sem controle de acesso
- ❌ Produção crítica sem medidas de segurança adicionais

---

**Configuração aplicada por padrão para facilitar o uso. Ajuste conforme necessário para seu ambiente.**
