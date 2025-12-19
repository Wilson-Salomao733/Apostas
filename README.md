# Integração com API Betfair

Este projeto fornece uma solução completa para conectar e usar a API da Betfair Exchange usando autenticação não interativa com certificados. **Inclui suporte completo para Docker!**

## 💾 **NOVO**: Sistema de Banco de Dados

O bot agora usa um **banco de dados SQLite** para armazenar todas as apostas e resultados de forma permanente!

📖 **[Leia o guia completo do banco de dados →](DATABASE_README.md)**

### Recursos do Banco:
- ✅ Todas as apostas são salvas automaticamente
- ✅ Histórico completo nunca é perdido
- ✅ Estatísticas diárias automáticas
- ✅ Consultas rápidas e eficientes
- ✅ Backup simples (apenas um arquivo: `data/bets.db`)

### Utilitários:
```bash
# Migrar dados antigos do JSON para o banco
python migrate_to_database.py

# Visualizar dados do banco
python view_database.py
```

---

## 📋 Pré-requisitos

### Para uso com Docker (Recomendado)
1. **Docker** e **Docker Compose** instalados
2. **Conta Betfair** ativa
3. **Application Key** da Betfair (obtenha em: https://developer.betfair.com/)

### Para uso local
1. **Python 3.7+** instalado
2. **OpenSSL** instalado (para gerar certificados)
3. **Conta Betfair** ativa
4. **Application Key** da Betfair (obtenha em: https://developer.betfair.com/)

---

## 🐳 Uso com Docker (Recomendado)

### Instalação Rápida

1. **Torne o script helper executável:**
```bash
chmod +x run.sh
```

2. **Construir a imagem Docker:**
```bash
./run.sh build
```

### Configuração Passo a Passo

#### Passo 1: Gerar Certificado Autoassinado

Execute dentro do container:
```bash
./run.sh generate-cert
```

Este comando irá:
- Gerar uma chave privada RSA de 2048 bits
- Criar um certificado autoassinado
- Gerar arquivos nos formatos .crt, .pem e .p12

**Arquivos criados em `certs/`:**
- `client-2048.key` - Chave privada (MANTENHA SEGURO!)
- `client-2048.crt` - Certificado (faça upload no Betfair)
- `client-2048.pem` - Certificado + chave
- `client-2048.p12` - Formato PKCS#12

#### Passo 2: Vincular Certificado à Conta Betfair

1. Acesse sua conta Betfair:
   - **Internacional:** https://myaccount.betfair.com/accountdetails/mysecurity?showAPI=1
   - **Austrália:** https://myaccount.betfair.com.au/accountdetails/mysecurity?showAPI=1
   - **Itália:** https://myaccount.betfair.it/accountdetails/mysecurity?showAPI=1
   - **Espanha:** https://myaccount.betfair.es/accountdetails/mysecurity?showAPI=1
   - **Romênia:** https://myaccount.betfair.ro/accountdetails/mysecurity?showAPI=1

2. Role até a seção **"Automated Betting Program Access"**
3. Clique em **"Edit"**
4. Clique em **"Browse"** e selecione o arquivo `certs/client-2048.crt`
5. Clique em **"Upload Certificate"**

#### Passo 3: Obter Application Key

1. Acesse: https://developer.betfair.com/
2. Faça login com sua conta Betfair
3. Crie uma nova aplicação ou use uma existente
4. Copie a **Application Key**

#### Passo 4: Configurar Credenciais

1. Copie o arquivo de exemplo:
```bash
cp config.ini.example config.ini
```

2. Edite o arquivo `config.ini` e preencha:
```ini
[betfair]
username = seu_usuario_betfair
password = sua_senha_betfair
app_key = sua_application_key
cert_file = certs/client-2048.crt
key_file = certs/client-2048.key
jurisdiction = com  # ou com.au, it, es, ro
```

### Comandos Docker Disponíveis

Use o script helper `run.sh` para facilitar:

```bash
./run.sh build          # Construir a imagem Docker
./run.sh up             # Iniciar o container
./run.sh down           # Parar o container
./run.sh logs           # Ver logs do container
./run.sh shell          # Abrir shell no container
./run.sh generate-cert  # Gerar certificado dentro do container
./run.sh login          # Testar login na API Betfair
./run.sh api            # Executar exemplo da API
```

### Testar Login

```bash
./run.sh login
```

Se tudo estiver correto, você verá:
```
✓ Login realizado com sucesso!
Session Token: xxxxxxxxxxxxxxxxxxxxxx
```

### Executar Exemplo da API

```bash
./run.sh api
```

### Usar Shell Interativo

Para executar comandos Python personalizados:
```bash
./run.sh shell
```

Dentro do shell:
```bash
python betfair_login.py
python betfair_api.py
python -c "from betfair_api import BetfairAPI; api = BetfairAPI(); api.login(); print(api.get_account_funds())"
```

### Comandos Docker Compose Diretos

Se preferir usar docker-compose diretamente:

```bash
# Construir
docker-compose build

# Iniciar container
docker-compose up -d

# Ver logs
docker-compose logs -f betfair-api

# Executar comando
docker-compose run --rm betfair-api python betfair_api.py

# Abrir shell
docker-compose run --rm betfair-api bash

# Parar
docker-compose down
```

---

## 💻 Uso Local (Sem Docker)

### Instalação

1. **Instale as dependências Python:**
```bash
pip install -r requirements.txt
```

2. **Instale o OpenSSL (se ainda não tiver):**
   - **Ubuntu/Debian:** `sudo apt-get install openssl`
   - **Fedora/CentOS:** `sudo yum install openssl`
   - **macOS:** `brew install openssl`

### Configuração Passo a Passo

Siga os mesmos passos descritos na seção Docker acima, mas execute os comandos localmente:

```bash
# Gerar certificado
bash generate_certificate.sh

# Configurar credenciais
cp config.ini.example config.ini
# Edite config.ini com suas credenciais
```

## 🎯 Uso

### Testar Login

Execute o script de login:

```bash
python betfair_login.py
```

Se tudo estiver correto, você verá:
```
✓ Login realizado com sucesso!
Session Token: xxxxxxxxxxxxxxxxxxxxxx
✓ Token salvo em: session_token.txt
```

### Usar a API

Execute o exemplo completo:

```bash
python betfair_api.py
```

Ou use programaticamente:

```python
from betfair_api import BetfairAPI

# Criar cliente
api = BetfairAPI()

# Fazer login
api.login()

# Obter fundos da conta
funds = api.get_account_funds()
print(f"Fundos disponíveis: {funds['availableToBetBalance']}")

# Listar tipos de eventos
event_types = api.list_event_types()
for event_type in event_types:
    print(event_type['eventType']['name'])

# Listar mercados de futebol
filter_dict = {
    'eventTypeIds': ['1'],  # 1 = Futebol
    'marketCountries': ['GB']
}
markets = api.list_market_catalogue(
    filter_dict=filter_dict,
    max_results=10
)
```

## 📚 Métodos Disponíveis na API

### Informações de Conta
- `get_account_funds()` - Obtém saldo e fundos disponíveis

### Listagens
- `list_event_types(filter_dict)` - Lista tipos de eventos
- `list_competitions(filter_dict)` - Lista competições
- `list_market_catalogue(filter_dict, ...)` - Lista catálogo de mercados
- `list_market_book(market_ids, ...)` - Obtém dados de mercado (odds)

### Operações
- `place_orders(market_id, instructions)` - Coloca ordens (apostas)

## 🔒 Segurança

⚠️ **IMPORTANTE:**
- **NUNCA** compartilhe sua chave privada (`client-2048.key`)
- **NUNCA** compartilhe arquivos `.pem` ou `.p12`
- Mantenha o arquivo `config.ini` seguro e não o compartilhe
- Adicione `config.ini` e `certs/` ao `.gitignore` se usar controle de versão

## 🐛 Solução de Problemas

### Erro: "CERT_AUTH_REQUIRED"
- Verifique se o certificado foi carregado corretamente no site da Betfair
- Certifique-se de que está usando o certificado correto (`.crt` e `.key`)
- Verifique se o usuário e senha estão corretos

### Erro: "INVALID_USERNAME_OR_PASSWORD"
- Verifique suas credenciais no `config.ini`
- Certifique-se de que o usuário e senha estão codificados corretamente

### Erro SSL
- Verifique se os arquivos de certificado existem
- Certifique-se de que o certificado foi vinculado à sua conta Betfair

### Erro: "Application Key inválida"
- Verifique se a Application Key está correta
- Certifique-se de que está usando a key no header `X-Application`

## 📖 Documentação Adicional

- [Documentação Oficial da API Betfair](https://docs.developer.betfair.com/)
- [Betfair Developer Portal](https://developer.betfair.com/)

## 📄 Licença

Este projeto é fornecido como está, apenas para fins educacionais e de integração com a API Betfair.

# Apostas
