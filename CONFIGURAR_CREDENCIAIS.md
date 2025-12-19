# 🔐 Como Configurar o config.ini

## 📝 O que você precisa:

1. **Username (usuário) da Betfair** - Seu nome de usuário para login
2. **Password (senha) da Betfair** - Sua senha para login
3. **Application Key** - Obtenha em https://developer.betfair.com/

---

## 🎯 Passo a Passo:

### **1. Abrir o arquivo config.ini**

Você pode usar qualquer editor de texto. Exemplos:

```bash
# Opção 1: Usar nano (editor simples no terminal)
nano config.ini

# Opção 2: Usar vim
vim config.ini

# Opção 3: Usar gedit (interface gráfica)
gedit config.ini

# Opção 4: Usar code (VS Code)
code config.ini
```

---

### **2. Editar as linhas 3, 6 e 9**

Substitua os valores de exemplo pelos seus dados reais:

```ini
[betfair]
# Seu nome de usuário da Betfair
username = SEU_USUARIO_AQUI          ← SUBSTITUA AQUI

# Sua senha da Betfair
password = SUA_SENHA_AQUI             ← SUBSTITUA AQUI

# Application Key (obtenha em: https://developer.betfair.com/)
app_key = SUA_APP_KEY_AQUI            ← SUBSTITUA AQUI
```

**Exemplo de como deve ficar:**
```ini
[betfair]
# Seu nome de usuário da Betfair
username = joao.silva

# Sua senha da Betfair
password = MinhaSenh@123

# Application Key (obtenha em: https://developer.betfair.com/)
app_key = abc123xyz456def789
```

---

### **3. Verificar os caminhos dos certificados**

Os caminhos já devem estar corretos:
```ini
cert_file = certs/client-2048.crt
key_file = certs/client-2048.key
```

**✅ NÃO PRECISA MUDAR** - Já estão corretos!

---

### **4. Verificar a jurisdição**

A jurisdição já está configurada como `com` (internacional):
```ini
jurisdiction = com
```

**Se você é de:**
- **Brasil/Internacional** → `com` ✅ (já está assim)
- **Austrália/Nova Zelândia** → `com.au`
- **Itália** → `it`
- **Espanha** → `es`
- **Romênia** → `ro`

**✅ Se você é do Brasil, NÃO PRECISA MUDAR!**

---

### **5. Salvar o arquivo**

- **No nano:** Pressione `Ctrl + X`, depois `Y`, depois `Enter`
- **No vim:** Pressione `Esc`, digite `:wq`, depois `Enter`
- **No gedit/VS Code:** Use `Ctrl + S` ou File → Save

---

## 🔑 Como Obter a Application Key:

1. **Acesse:** https://developer.betfair.com/
2. **Faça login** com sua conta Betfair
3. Vá em **"My Applications"** ou **"Applications"**
4. **Crie uma nova aplicação** ou use uma existente
5. **Copie a Application Key** (geralmente é uma string longa como "abc123xyz...")

---

## ✅ Verificar se está correto:

Depois de configurar, o arquivo deve ter algo assim:

```ini
[betfair]
# Seu nome de usuário da Betfair
username = seu_usuario_real
password = sua_senha_real
app_key = sua_app_key_real
cert_file = certs/client-2048.crt
key_file = certs/client-2048.key
jurisdiction = com
```

**⚠️ IMPORTANTE:**
- Não deixe espaços antes ou depois do `=`
- Não use aspas nos valores
- Mantenha os comentários (linhas que começam com `#`)

---

## 🧪 Testar a Configuração:

Depois de configurar, teste:

```bash
python3 betfair_login.py
```

Se aparecer:
```
✓ Login realizado com sucesso!
Session Token: xxxxxxxxxxxxxx
```

**✅ Está tudo certo!**

Se aparecer erro, verifique:
- Se o certificado foi carregado no Betfair
- Se o usuário e senha estão corretos
- Se a Application Key está correta

---

## 💡 Dica:

Se você não quiser editar manualmente, posso criar um script interativo que pergunta os valores e configura automaticamente. Me avise se quiser!

