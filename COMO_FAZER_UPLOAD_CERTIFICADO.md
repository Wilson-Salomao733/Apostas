# 📤 Como Fazer Upload do Certificado no Betfair

## ⚠️ Erro: CERT_AUTH_REQUIRED

Este erro significa que o certificado **não foi carregado** ou **não foi aceito** no site da Betfair.

---

## 🎯 Passo a Passo para Fazer Upload

### **1. Acesse sua Conta Betfair**

**Para clientes brasileiros:**
- https://www.betfair.bet.br
- Faça login com suas credenciais

**Para outros países:**
- https://myaccount.betfair.com/accountdetails/mysecurity?showAPI=1
- https://myaccount.betfair.com.au/accountdetails/mysecurity?showAPI=1 (Austrália)
- https://myaccount.betfair.it/accountdetails/mysecurity?showAPI=1 (Itália)
- https://myaccount.betfair.es/accountdetails/mysecurity?showAPI=1 (Espanha)
- https://myaccount.betfair.ro/accountdetails/mysecurity?showAPI=1 (Romênia)

---

### **2. Navegue até a Seção de Segurança**

1. Vá em **"Minha Conta"** ou **"Account Details"**
2. Procure por **"Segurança"** ou **"Security"**
3. Role até encontrar **"Automated Betting Program Access"** ou **"Acesso ao Programa de Apostas Automatizadas"**

---

### **3. Faça Upload do Certificado**

1. Clique em **"Edit"** ou **"Editar"**
2. Clique em **"Browse"** ou **"Procurar"**
3. **Selecione o arquivo:** `certs/client-2048.crt`
   - **Caminho completo:** `/home/wilsonsalomo/Documentos/JOGOS_APOSTAS/certs/client-2048.crt`
4. Clique em **"Upload Certificate"** ou **"Enviar Certificado"**

---

### **4. Verifique o Upload**

Após o upload, você deve ver:
- ✅ O certificado listado na seção "Automated Betting Program Access"
- ✅ Detalhes do certificado (data de criação, etc.)

---

### **5. Aguarde Alguns Minutos**

Às vezes leva alguns minutos para o certificado ser processado. Aguarde 2-5 minutos antes de tentar fazer login novamente.

---

## 🔍 Verificar se o Certificado Está Correto

### **Verificar o arquivo:**

```bash
# Verificar se o arquivo existe
ls -lh certs/client-2048.crt

# Ver detalhes do certificado
openssl x509 -in certs/client-2048.crt -text -noout | head -30
```

**O certificado deve mostrar:**
- Subject: CN = Betfair API-NG Certificate
- Validity: Válido por 365 dias
- Signature Algorithm: sha256WithRSAEncryption

---

## ⚠️ Problemas Comuns

### **Problema 1: "Certificado inválido"**

**Solução:**
- Certifique-se de que está fazendo upload do arquivo `.crt` (não `.key`, `.pem` ou `.p12`)
- Verifique se o certificado foi gerado corretamente
- Tente gerar um novo certificado: `bash generate_certificate.sh`

### **Problema 2: "Certificado já existe"**

**Solução:**
- Se você já tem um certificado carregado, pode precisar removê-lo primeiro
- Ou use o certificado existente (se você tiver o arquivo `.key` correspondente)

### **Problema 3: "Não encontro a seção Automated Betting Program Access"**

**Solução:**
- Certifique-se de estar logado na conta correta
- Verifique se sua conta tem permissão para usar a API
- Tente acessar diretamente: `https://myaccount.betfair.com/accountdetails/mysecurity?showAPI=1`

### **Problema 4: "Ainda recebo CERT_AUTH_REQUIRED após upload"**

**Soluções:**
1. **Aguarde alguns minutos** - pode levar tempo para processar
2. **Verifique se está usando o certificado correto:**
   - O `.crt` no Betfair deve corresponder ao `.key` no seu computador
   - Se gerou um novo certificado, precisa fazer upload do novo `.crt`
3. **Verifique o username:**
   - Certifique-se de que o username no `config.ini` está correto
   - Pode ser necessário usar email em vez de username
4. **Tente fazer logout e login novamente** no site da Betfair
5. **Gere um novo certificado** e faça upload novamente

---

## 🧪 Testar Após Upload

Depois de fazer upload e aguardar alguns minutos:

```bash
python3 betfair_login.py
```

**Sucesso esperado:**
```
=== Login na API Betfair ===

✓ Login realizado com sucesso!
Session Token: xxxxxxxxxxxxxxxxxxxxxx

✓ Token salvo em: session_token.txt
```

---

## 📝 Checklist

Antes de tentar fazer login, verifique:

- [ ] Certificado foi gerado (`certs/client-2048.crt` existe)
- [ ] Certificado foi carregado no site da Betfair
- [ ] Certificado aparece na lista no site da Betfair
- [ ] Aguardou alguns minutos após o upload
- [ ] Username no `config.ini` está correto
- [ ] Password no `config.ini` está correta
- [ ] App Key no `config.ini` está correta
- [ ] Jurisdiction no `config.ini` está correta

---

## 💡 Dica

Se você já fez upload do certificado antes e ainda recebe erro, pode ser que:
- O certificado expirou (válido por 365 dias)
- Você gerou um novo certificado mas não fez upload
- Há um problema com a conta

**Solução:** Gere um novo certificado e faça upload novamente.

---

## 🔄 Gerar Novo Certificado (se necessário)

Se precisar gerar um novo certificado:

```bash
bash generate_certificate.sh
```

Depois faça upload do novo `certs/client-2048.crt` no Betfair.

---

**Boa sorte! 🍀**

