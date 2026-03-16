# 🎯 COMECE AQUI - API Betfair

## ✅ O que já está pronto:

1. ✅ Código Python completo para login e uso da API
2. ✅ Script para gerar certificado autoassinado
3. ✅ Arquivos de configuração
4. ✅ Exemplos de uso

## 🚀 COMEÇAR AGORA (3 passos rápidos):

### **OPÇÃO 1: Setup Automático (Recomendado)**

```bash
bash setup.sh
```

Este script vai:
- Verificar se Python e OpenSSL estão instalados
- Instalar dependências
- Criar ambiente virtual (opcional)
- Gerar certificado (opcional)
- Verificar configuração

---

### **OPÇÃO 2: Passo a Passo Manual**

#### **1. Instalar dependências:**
```bash
pip install -r requirements.txt
```

#### **2. Gerar certificado:**
```bash
bash generate_certificate.sh
```

#### **3. Configurar credenciais:**
Edite `config.ini` com suas informações:
- `username` = seu usuário Betfair
- `password` = sua senha Betfair  
- `app_key` = sua Application Key (obtenha em https://developer.betfair.com/)

---

## 📝 PRÓXIMOS PASSOS OBRIGATÓRIOS:

### **1. Fazer Upload do Certificado no Betfair**

1. Acesse: https://myaccount.betfair.com/accountdetails/mysecurity?showAPI=1
2. Faça login
3. Vá em **"Automated Betting Program Access"** → **"Edit"**
4. Faça upload do arquivo: `certs/client-2048.crt`
5. Clique em **"Upload Certificate"**

### **2. Obter Application Key**

1. Acesse: https://developer.betfair.com/
2. Faça login
3. Crie uma aplicação ou use uma existente
4. Copie a **Application Key**

### **3. Configurar `config.ini`**

Abra o arquivo `config.ini` e preencha:
```ini
username = SEU_USUARIO
password = SUA_SENHA
app_key = SUA_APP_KEY
```

---

## 🧪 TESTAR:

### **Testar Login:**
```bash
python3 betfair_login.py
```

**Sucesso esperado:**
```
✓ Login realizado com sucesso!
Session Token: xxxxxxxxxxxxxx
```

### **Testar API:**
```bash
python3 betfair_api.py
```

Ou veja exemplos completos:
```bash
python3 example_usage.py
```

---

## 📚 Documentação:

- **Guia Completo:** `GUIA_RAPIDO.md`
- **README Completo:** `README.md`
- **Exemplo de Uso:** `example_usage.py`

---

## ⚠️ Problemas Comuns:

### Erro: "CERT_AUTH_REQUIRED"
→ Certificado não foi carregado no Betfair ou está incorreto

### Erro: "INVALID_USERNAME_OR_PASSWORD"  
→ Verifique usuário/senha no `config.ini`

### Erro: "FileNotFoundError"
→ Execute `bash generate_certificate.sh` primeiro

---

## 💡 Dica Rápida:

Se você já tem tudo configurado, pode testar diretamente:

```bash
python3 betfair_login.py
```

Se funcionar, você está pronto para usar a API! 🎉

---

**Precisa de ajuda? Consulte `GUIA_RAPIDO.md` para instruções detalhadas!**

