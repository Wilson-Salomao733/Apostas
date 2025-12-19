#!/usr/bin/env python3
"""
Teste direto da API para verificar qual endpoint funciona
"""

import requests
import json
from betfair_login import BetfairLogin

# Fazer login
login = BetfairLogin()
result = login.login()

if result.get('loginStatus') != 'SUCCESS':
    print("Erro no login")
    exit(1)

token = result.get('sessionToken')
app_key = login.app_key

print(f"Token: {token[:50]}...")
print(f"App Key: {app_key}")
print()

# Testar diferentes endpoints
endpoints = [
    'https://api.betfair.com/exchange/betting/json-rpc/v1',
    'https://api.betfair.com/exchange/account/json-rpc/v1',
    'https://api.betfair.bet.br/exchange/betting/json-rpc/v1',
    'https://api.betfair.bet.br/exchange/account/json-rpc/v1',
]

headers = {
    'X-Application': app_key,
    'X-Authentication': token,
    'Content-Type': 'application/json'
}

payload = {
    'jsonrpc': '2.0',
    'method': 'AccountAPING/v1.0/getAccountFunds',
    'params': {},
    'id': 1
}

for endpoint in endpoints:
    print(f"Testando: {endpoint}")
    try:
        response = requests.post(endpoint, json=payload, headers=headers, timeout=10)
        print(f"  Status: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            print(f"  ✓ SUCESSO!")
            print(f"  Resposta: {json.dumps(result, indent=2)[:200]}...")
            break
        else:
            print(f"  ✗ Erro: {response.text[:200]}")
    except Exception as e:
        print(f"  ✗ Exceção: {str(e)[:200]}")
    print()

