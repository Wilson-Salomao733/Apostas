#!/usr/bin/env python3
"""
Script para fazer login não interativo na API Betfair usando certificado
"""

import requests
import json
import os
from urllib.parse import urlencode
from configparser import ConfigParser

class BetfairLogin:
    def __init__(self, config_file='config.ini'):
        """
        Inicializa o cliente de login Betfair
        
        Args:
            config_file: Caminho para o arquivo de configuração
        """
        self.config = ConfigParser()
        self.config.read(config_file)
        
        # Carregar configurações
        self.username = self.config.get('betfair', 'username')
        self.password = self.config.get('betfair', 'password')
        self.app_key = self.config.get('betfair', 'app_key')
        self.cert_file = self.config.get('betfair', 'cert_file')
        self.key_file = self.config.get('betfair', 'key_file')
        
        # Endpoint baseado na jurisdição
        jurisdiction = self.config.get('betfair', 'jurisdiction', fallback='com')
        # Suporte para domínio brasileiro
        if jurisdiction == 'br' or jurisdiction == 'bet.br':
            self.endpoint = "https://identitysso-cert.betfair.bet.br/api/certlogin"
        else:
            self.endpoint = f"https://identitysso-cert.betfair.{jurisdiction}/api/certlogin"
        
    def login(self):
        """
        Faz login na API Betfair e retorna o token de sessão
        
        Returns:
            dict: Resposta do login contendo sessionToken e loginStatus
        """
        # Preparar payload
        payload = {
            'username': self.username,
            'password': self.password
        }
        
        # Preparar headers
        headers = {
            'X-Application': self.app_key,
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        # Verificar se os arquivos de certificado existem
        if not os.path.exists(self.cert_file):
            raise FileNotFoundError(f"Arquivo de certificado não encontrado: {self.cert_file}")
        
        if not os.path.exists(self.key_file):
            raise FileNotFoundError(f"Arquivo de chave não encontrado: {self.key_file}")
        
        # Fazer requisição POST com certificado
        try:
            response = requests.post(
                self.endpoint,
                data=payload,
                cert=(self.cert_file, self.key_file),
                headers=headers,
                verify=True
            )
            
            response.raise_for_status()
            
            # Parse da resposta JSON
            result = response.json()
            
            if result.get('loginStatus') == 'SUCCESS':
                print("✓ Login realizado com sucesso!")
                print(f"Session Token: {result.get('sessionToken')}")
                return result
            else:
                error_msg = result.get('loginStatus', 'UNKNOWN_ERROR')
                print(f"✗ Erro no login: {error_msg}")
                return result
                
        except requests.exceptions.SSLError as e:
            print(f"✗ Erro SSL: {e}")
            print("Verifique se o certificado está correto e foi vinculado à sua conta Betfair.")
            raise
        except requests.exceptions.RequestException as e:
            print(f"✗ Erro na requisição: {e}")
            raise
        except json.JSONDecodeError as e:
            print(f"✗ Erro ao decodificar resposta JSON: {e}")
            print(f"Resposta recebida: {response.text}")
            raise
    
    def get_session_token(self):
        """
        Retorna apenas o token de sessão
        
        Returns:
            str: Token de sessão ou None em caso de erro
        """
        result = self.login()
        if result.get('loginStatus') == 'SUCCESS':
            return result.get('sessionToken')
        return None


def main():
    """Função principal"""
    print("=== Login na API Betfair ===\n")
    
    try:
        # Criar instância do cliente
        client = BetfairLogin()
        
        # Fazer login
        result = client.login()
        
        # Salvar token em arquivo se login foi bem-sucedido
        if result.get('loginStatus') == 'SUCCESS':
            token = result.get('sessionToken')
            with open('session_token.txt', 'w') as f:
                f.write(token)
            print(f"\n✓ Token salvo em: session_token.txt")
            
            return token
        else:
            return None
            
    except FileNotFoundError as e:
        print(f"\n✗ {e}")
        print("\nCertifique-se de que:")
        print("1. O arquivo config.ini existe e está configurado corretamente")
        print("2. Os arquivos de certificado foram gerados (execute generate_certificate.sh)")
        return None
    except Exception as e:
        print(f"\n✗ Erro: {e}")
        return None


if __name__ == '__main__':
    main()

