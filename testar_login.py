#!/usr/bin/env python3
"""
Script de diagnóstico para testar login na Betfair
"""

import requests
import json
import os
from configparser import ConfigParser

def testar_login():
    """Testa login com diferentes configurações"""
    
    config = ConfigParser()
    config.read('config.ini')
    
    username = config.get('betfair', 'username')
    password = config.get('betfair', 'password')
    app_key = config.get('betfair', 'app_key')
    cert_file = config.get('betfair', 'cert_file')
    key_file = config.get('betfair', 'key_file')
    jurisdiction = config.get('betfair', 'jurisdiction', fallback='com')
    
    print("=" * 60)
    print("DIAGNÓSTICO DE LOGIN BETFAIR")
    print("=" * 60)
    print()
    
    # Verificar arquivos
    print("1. Verificando arquivos...")
    if not os.path.exists(cert_file):
        print(f"   ✗ Certificado não encontrado: {cert_file}")
        return
    print(f"   ✓ Certificado encontrado: {cert_file}")
    
    if not os.path.exists(key_file):
        print(f"   ✗ Chave não encontrada: {key_file}")
        return
    print(f"   ✓ Chave encontrada: {key_file}")
    print()
    
    # Testar diferentes endpoints
    endpoints = []
    
    # Para Brasil, pode precisar de endpoint diferente
    if jurisdiction == 'com':
        endpoints = [
            ('com', 'https://identitysso-cert.betfair.com/api/certlogin'),
            ('bet.br', 'https://identitysso-cert.betfair.bet.br/api/certlogin'),
        ]
    else:
        endpoints = [(jurisdiction, f'https://identitysso-cert.betfair.{jurisdiction}/api/certlogin')]
    
    # Testar diferentes formatos de username
    usernames_to_try = [
        username,  # Original
        username.lower(),  # Minúsculas
        username.replace(' ', ''),  # Sem espaços
        username.replace(' ', '.'),  # Espaços como pontos
    ]
    
    print("2. Testando login...")
    print()
    
    for juris, endpoint in endpoints:
        print(f"   Testando endpoint: {endpoint}")
        
        for test_username in usernames_to_try:
            if test_username == username and juris != endpoints[0][0]:
                continue  # Evitar duplicatas
            
            print(f"   - Username: '{test_username}'")
            
            payload = {
                'username': test_username,
                'password': password
            }
            
            headers = {
                'X-Application': app_key,
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            try:
                response = requests.post(
                    endpoint,
                    data=payload,
                    cert=(cert_file, key_file),
                    headers=headers,
                    verify=True,
                    timeout=10
                )
                
                result = response.json()
                login_status = result.get('loginStatus', 'UNKNOWN')
                
                if login_status == 'SUCCESS':
                    print(f"   ✓✓✓ SUCESSO! ✓✓✓")
                    print(f"   Token: {result.get('sessionToken', 'N/A')}")
                    print(f"   Endpoint correto: {endpoint}")
                    print(f"   Username correto: '{test_username}'")
                    return result
                else:
                    print(f"   ✗ Erro: {login_status}")
                    if login_status != 'CERT_AUTH_REQUIRED':
                        print(f"      (Este erro é diferente de CERT_AUTH_REQUIRED)")
                    
            except requests.exceptions.SSLError as e:
                print(f"   ✗ Erro SSL: {str(e)[:100]}")
            except Exception as e:
                print(f"   ✗ Erro: {str(e)[:100]}")
        
        print()
    
    print("=" * 60)
    print("Nenhuma combinação funcionou.")
    print()
    print("Possíveis problemas:")
    print("1. Certificado no Betfair não corresponde ao certificado local")
    print("2. Username incorreto (tente usar email)")
    print("3. Password incorreta")
    print("4. Application Key incorreta")
    print("5. Certificado precisa ser reprocessado (aguarde alguns minutos)")
    print("=" * 60)

if __name__ == '__main__':
    testar_login()

