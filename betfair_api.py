#!/usr/bin/env python3
"""
Cliente básico para interagir com a API Betfair Exchange
"""

import requests
import json
import logging
from configparser import ConfigParser
from betfair_login import BetfairLogin

class BetfairAPI:
    def __init__(self, config_file='config.ini'):
        """
        Inicializa o cliente da API Betfair
        
        Args:
            config_file: Caminho para o arquivo de configuração
        """
        self.config = ConfigParser()
        self.config.read(config_file)
        
        self.app_key = self.config.get('betfair', 'app_key')
        self.jurisdiction = self.config.get('betfair', 'jurisdiction', fallback='com')
        
        # Endpoint da API Exchange
        if self.jurisdiction == 'com.au':
            self.api_endpoint = 'https://api-au.betfair.com/exchange/betting/json-rpc/v1'
        elif self.jurisdiction == 'it':
            self.api_endpoint = 'https://api-it.betfair.com/exchange/betting/json-rpc/v1'
        elif self.jurisdiction == 'es':
            self.api_endpoint = 'https://api-es.betfair.com/exchange/betting/json-rpc/v1'
        elif self.jurisdiction == 'ro':
            self.api_endpoint = 'https://api-ro.betfair.com/exchange/betting/json-rpc/v1'
        elif self.jurisdiction == 'br' or self.jurisdiction == 'bet.br':
            # Endpoint específico para Brasil (pode não estar disponível)
            # Usaremos fallback para endpoint internacional se falhar
            self.api_endpoint = 'https://api.betfair.bet.br/exchange/betting/json-rpc/v1'
            self.account_endpoint = 'https://api.betfair.bet.br/exchange/account/json-rpc/v1'
            self.fallback_endpoint = 'https://api.betfair.com/exchange/betting/json-rpc/v1'
            self.fallback_account_endpoint = None
        else:
            self.api_endpoint = 'https://api.betfair.com/exchange/betting/json-rpc/v1'
            self.account_endpoint = None
            self.fallback_endpoint = None
            self.fallback_account_endpoint = None
        
        self.session_token = None
        
    def login(self):
        """Faz login e obtém o token de sessão"""
        login_client = BetfairLogin()
        self.session_token = login_client.get_session_token()
        return self.session_token is not None
    
    def set_session_token(self, token):
        """Define o token de sessão manualmente"""
        self.session_token = token
    
    def _make_request(self, method, params=None, endpoint=None, max_retries=3):
        """
        Faz uma requisição à API Betfair com retry automático
        
        Args:
            method: Nome do método da API
            params: Parâmetros do método
            endpoint: Endpoint customizado (opcional)
            max_retries: Número máximo de tentativas em caso de erro de rede
            
        Returns:
            dict: Resposta da API
        """
        if not self.session_token:
            raise Exception("Token de sessão não encontrado. Execute login() primeiro.")
        
        headers = {
            'X-Application': self.app_key,
            'X-Authentication': self.session_token,
            'Content-Type': 'application/json'
        }
        
        payload = {
            'jsonrpc': '2.0',
            'method': method,
            'params': params or {},
            'id': 1
        }
        
        # Log detalhado para placeOrders (debug)
        if 'placeOrders' in method:
            import json
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"DEBUG placeOrders - Payload completo: {json.dumps(payload, indent=2, default=str)}")
        
        # Usar endpoint customizado se fornecido, senão usar o padrão
        api_endpoint = endpoint or self.api_endpoint
        
        # Retry logic para erros de rede/DNS
        import time
        import logging
        logger = logging.getLogger(__name__)
        last_exception = None
        
        # Tentar endpoint principal primeiro
        endpoints_to_try = [api_endpoint]
        
        # Se houver fallback e for erro de DNS, tentar fallback
        if hasattr(self, 'fallback_endpoint') and self.fallback_endpoint and api_endpoint == self.api_endpoint:
            endpoints_to_try.append(self.fallback_endpoint)
        
        for endpoint_to_use in endpoints_to_try:
            for attempt in range(max_retries):
                try:
                    response = requests.post(
                        endpoint_to_use,
                        json=payload,
                        headers=headers,
                        timeout=30  # Timeout de 30 segundos
                    )
                    
                    response.raise_for_status()
                    result = response.json()
                    
                    if 'error' in result:
                        # Erros da API não devem ser retentados (exceto alguns casos específicos)
                        error_code = result.get('error', {}).get('code', '')
                        error_message = result.get('error', {}).get('message', '')
                        error_data = result.get('error', {}).get('data', {})
                        
                        # Verificar se é erro de sessão inválida
                        if 'INVALID_SESSION_INFORMATION' in str(error_data) or 'INVALID_SESSION' in str(error_message):
                            logger.warning("Token de sessão inválido ou expirado. Tentando fazer novo login...")
                            # Tentar fazer novo login
                            if self.login():
                                logger.info("✓ Novo login realizado com sucesso. Tentando novamente a requisição...")
                                # Atualizar headers com novo token
                                headers['X-Authentication'] = self.session_token
                                # Tentar novamente a requisição (apenas uma vez)
                                response = requests.post(
                                    endpoint_to_use,
                                    json=payload,
                                    headers=headers,
                                    timeout=30
                                )
                                response.raise_for_status()
                                result = response.json()
                                if 'error' in result:
                                    raise Exception(f"Erro da API após re-login: {result['error']}")
                                return result.get('result', {})
                            else:
                                raise Exception("Falha ao fazer novo login após token expirado")
                        
                        # DSC-0018 é erro de parâmetros inválidos, não deve retentar
                        if 'DSC-0018' in str(error_message):
                            raise Exception(f"Erro da API: {result['error']}")
                        
                        # Outros erros podem ser temporários, mas vamos tratar como permanente por enquanto
                        raise Exception(f"Erro da API: {result['error']}")
                    
                    # Se chegou aqui, a requisição foi bem-sucedida
                    # Se estava usando fallback, atualizar o endpoint principal
                    if endpoint_to_use != api_endpoint and endpoint_to_use == self.fallback_endpoint:
                        logger.info(f"✓ Usando endpoint fallback: {endpoint_to_use}")
                        self.api_endpoint = endpoint_to_use
                    
                    return result.get('result', {})
                    
                except (requests.exceptions.ConnectionError, 
                        requests.exceptions.Timeout,
                        requests.exceptions.RequestException) as e:
                    last_exception = e
                    error_str = str(e)
                    
                    # Verificar se é erro de DNS
                    if 'Failed to resolve' in error_str or 'NameResolutionError' in error_str:
                        # Se é o primeiro endpoint e há fallback, tentar fallback imediatamente
                        if endpoint_to_use == api_endpoint and len(endpoints_to_try) > 1:
                            logger.warning(f"Erro de DNS com endpoint brasileiro. Tentando endpoint internacional...")
                            break  # Sair do loop de tentativas e tentar próximo endpoint
                        
                        if attempt < max_retries - 1:
                            wait_time = (attempt + 1) * 2  # Backoff exponencial: 2s, 4s, 6s
                            logger.warning(f"Erro de DNS ao conectar com {endpoint_to_use}. Tentativa {attempt + 1}/{max_retries}. Aguardando {wait_time}s...")
                            time.sleep(wait_time)
                            continue
                        else:
                            # Se é o último endpoint, lançar erro
                            if endpoint_to_use == endpoints_to_try[-1]:
                                logger.error(f"Erro de DNS após {max_retries} tentativas em todos os endpoints: {e}")
                                raise Exception(f"Erro de conexão com a API (DNS): {e}")
                            # Senão, tentar próximo endpoint
                            break
                    else:
                        # Outros erros de rede
                        if attempt < max_retries - 1:
                            wait_time = (attempt + 1) * 2
                            logger.warning(f"Erro de rede ao conectar com {endpoint_to_use}. Tentativa {attempt + 1}/{max_retries}. Aguardando {wait_time}s...")
                            time.sleep(wait_time)
                            continue
                        else:
                            # Se é o último endpoint, lançar erro
                            if endpoint_to_use == endpoints_to_try[-1]:
                                raise
                            # Senão, tentar próximo endpoint
                            break
        
        # Se chegou aqui, todas as tentativas falharam
        if last_exception:
            raise last_exception
        raise Exception("Erro desconhecido na requisição")
    
    def list_event_types(self, filter_dict=None):
        """
        Lista tipos de eventos disponíveis
        
        Args:
            filter_dict: Filtros opcionais
            
        Returns:
            list: Lista de tipos de eventos
        """
        params = {
            'filter': filter_dict or {}
        }
        return self._make_request('SportsAPING/v1.0/listEventTypes', params)
    
    def list_competitions(self, filter_dict=None):
        """
        Lista competições disponíveis
        
        Args:
            filter_dict: Filtros opcionais
            
        Returns:
            list: Lista de competições
        """
        params = {
            'filter': filter_dict or {}
        }
        return self._make_request('SportsAPING/v1.0/listCompetitions', params)
    
    def list_market_catalogue(self, filter_dict=None, market_projection=None, 
                             sort=None, max_results=1000):
        """
        Lista catálogo de mercados
        
        Args:
            filter_dict: Filtros de mercado
            market_projection: Projeções de mercado
            sort: Ordenação
            max_results: Número máximo de resultados
            
        Returns:
            list: Lista de mercados
        """
        params = {
            'filter': filter_dict or {},
            'marketProjection': market_projection or [],
            'sort': sort,
            'maxResults': max_results if max_results and max_results > 0 else 1000  # Garantir que sempre tenha um valor válido
        }
        
        # Remover campos None para evitar problemas
        params = {k: v for k, v in params.items() if v is not None}
        return self._make_request('SportsAPING/v1.0/listMarketCatalogue', params)
    
    def list_market_book(self, market_ids, price_projection=None, 
                        order_projection=None, match_projection=None):
        """
        Obtém dados de mercado (odds, volumes, etc.)
        
        Args:
            market_ids: Lista de IDs de mercado
            price_projection: Projeção de preços
            order_projection: Projeção de ordens
            match_projection: Projeção de correspondências
            
        Returns:
            list: Lista de dados de mercado
        """
        params = {
            'marketIds': market_ids,
            'priceProjection': price_projection or {},
            'orderProjection': order_projection,
            'matchProjection': match_projection
        }
        return self._make_request('SportsAPING/v1.0/listMarketBook', params)
    
    def place_orders(self, market_id, instructions, customer_ref=None):
        """
        Coloca ordens (apostas) no mercado
        
        Args:
            market_id: ID do mercado
            instructions: Lista de instruções de ordem
            customer_ref: Referência do cliente (opcional)
            
        Returns:
            dict: Resultado das ordens
        """
        # Validar que instructions não está vazio
        if not instructions or len(instructions) == 0:
            raise ValueError("instructions não pode estar vazio")
        
        # Validar e limpar cada instrução
        cleaned_instructions = []
        for instruction in instructions:
            # Verificar campos obrigatórios
            required_fields = ['instructionType', 'side', 'orderType', 'selectionId']
            for field in required_fields:
                if field not in instruction:
                    raise ValueError(f"Campo obrigatório '{field}' não encontrado na instrução")
            
            # Limpar a instrução - remover campos None e garantir tipos corretos
            cleaned_instruction = {}
            for key, value in instruction.items():
                if value is not None:
                    # Garantir tipos corretos
                    if key == 'selectionId':
                        cleaned_instruction[key] = int(value)
                    elif key == 'handicap':
                        # IMPORTANTE: Para Match Odds, NUNCA enviar handicap
                        # Handicap só deve ser incluído para mercados específicos como Asian Handicap
                        # Se o valor for 0.0 ou None, não incluir
                        # Por segurança, só incluir se for explicitamente diferente de 0 e não None
                        if value is not None and value != 0 and value != 0.0:
                            cleaned_instruction[key] = float(value)
                        # Se for 0, None ou 0.0, não incluir (será omitido)
                    elif key == 'limitOrder' and isinstance(value, dict):
                        # Limpar limitOrder
                        cleaned_limit = {}
                        for lk, lv in value.items():
                            if lv is not None:
                                if lk in ['size', 'price']:
                                    # Validar que price está no range válido (1.01 a 1000)
                                    if lk == 'price':
                                        price_val = float(lv)
                                        if price_val < 1.01 or price_val > 1000:
                                            raise ValueError(f"Price inválido: {price_val} (deve estar entre 1.01 e 1000)")
                                        # Arredondar price para 2 casas decimais
                                        cleaned_limit[lk] = round(price_val, 2)
                                    else:  # size
                                        size_val = float(lv)
                                        if size_val <= 0:
                                            raise ValueError(f"Size inválido: {size_val} (deve ser maior que 0)")
                                        # Arredondar size para 2 casas decimais
                                        cleaned_limit[lk] = round(size_val, 2)
                                else:
                                    cleaned_limit[lk] = lv
                        cleaned_instruction[key] = cleaned_limit
                    else:
                        cleaned_instruction[key] = value
            
            cleaned_instructions.append(cleaned_instruction)
        
        # Garantir que customerRef seja string vazia se None
        params = {
            'marketId': str(market_id),  # Garantir que seja string
            'instructions': cleaned_instructions,
            'customerRef': customer_ref if customer_ref else ''  # Sempre string, nunca None
        }
        
        return self._make_request('SportsAPING/v1.0/placeOrders', params)
    
    def cancel_orders(self, market_id, bet_ids=None, instructions=None, customer_ref=None):
        """
        Cancela ordens (apostas) no mercado
        
        Args:
            market_id: ID do mercado
            bet_ids: Lista de IDs de apostas para cancelar (opcional)
            instructions: Lista de instruções de cancelamento (opcional)
            customer_ref: Referência do cliente (opcional)
            
        Returns:
            dict: Resultado do cancelamento
        """
        params = {
            'marketId': market_id,
            'customerRef': customer_ref or ''
        }
        
        if bet_ids:
            instructions = [{'betId': bet_id} for bet_id in bet_ids]
        
        if instructions:
            params['instructions'] = instructions
        
        return self._make_request('SportsAPING/v1.0/cancelOrders', params)
    
    def get_account_funds(self):
        """
        Obtém informações sobre fundos da conta
        
        Returns:
            dict: Informações de fundos
        """
        # Para Brasil, usar endpoint de Account separado se disponível
        if hasattr(self, 'account_endpoint') and self.account_endpoint:
            return self._make_request('AccountAPING/v1.0/getAccountFunds', {}, endpoint=self.account_endpoint)
        return self._make_request('AccountAPING/v1.0/getAccountFunds', {})
    
    def list_current_orders(self, bet_ids=None, market_ids=None, order_projection=None):
        """
        Lista ordens (apostas) atuais
        
        Args:
            bet_ids: Lista de IDs de apostas (opcional)
            market_ids: Lista de IDs de mercados (opcional)
            order_projection: Projeção de ordens (opcional)
            
        Returns:
            dict: Resultado com ordens atuais
        """
        params = {}
        
        if bet_ids:
            params['betIds'] = bet_ids
        
        if market_ids:
            params['marketIds'] = market_ids
        
        if order_projection:
            params['orderProjection'] = order_projection
        
        return self._make_request('SportsAPING/v1.0/listCurrentOrders', params)
    
    def get_settled_bets(self, bet_ids=None, from_date=None, to_date=None, page_index=0):
        """
        Busca apostas finalizadas (settled) da API de atividade da Betfair
        
        Args:
            bet_ids: Lista de IDs de apostas (opcional)
            from_date: Data inicial (opcional)
            to_date: Data final (opcional)
            page_index: Índice da página (padrão 0)
            
        Returns:
            dict: Dados das apostas finalizadas
        """
        try:
            # URL da API de atividade da Betfair Brasil
            base_url = 'https://myactivity.betfair.bet.br/activity/exchange/settled'
            
            # Preparar headers com autenticação
            headers = {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
            }
            
            # Se tiver session token, tentar usar (pode não funcionar para API web)
            if self.session_token:
                headers['Authorization'] = f'Bearer {self.session_token}'
            
            # Parâmetros da requisição
            params = {
                'pageIndex': page_index,
                'pageSize': 10
            }
            
            if bet_ids:
                params['betIds'] = ','.join(bet_ids)
            
            # Fazer requisição
            response = requests.get(
                base_url,
                params=params,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                # Se falhar com autenticação, tentar sem (pode precisar de cookies de sessão)
                logging.getLogger(__name__).warning(
                    f"Erro ao buscar apostas finalizadas: {response.status_code}. "
                    "Pode ser necessário autenticação via cookies."
                )
                return None
                
        except Exception as e:
            logging.getLogger(__name__).error(f"Erro ao buscar apostas finalizadas: {e}")
            return None
    
    def get_market_result(self, market_id):
        """
        Busca resultado/placar de um mercado/jogo
        
        Args:
            market_id: ID do mercado
            
        Returns:
            dict: Dados do resultado do jogo (placar, status, etc.)
        """
        try:
            # Usar listMarketBook para obter status do mercado e runners
            market_book = self.list_market_book(
                market_ids=[market_id],
                match_projection='ROLLED_UP_BY_PRICE'
            )
            
            if not market_book:
                return None
            
            market = market_book[0]
            market_status = market.get('status')
            
            # Buscar informações do mercado
            market_catalogue = self.list_market_catalogue(
                filter_dict={'marketIds': [market_id]},
                market_projection=['MARKET_DESCRIPTION', 'RUNNER_DESCRIPTION', 'EVENT']
            )
            
            result = {
                'market_id': market_id,
                'market_status': market_status,
                'runners': []
            }
            
            if market_catalogue:
                market_info = market_catalogue[0] if market_catalogue else {}
                event = market_info.get('event', {})
                result['event_name'] = event.get('name', '')
                result['event_id'] = event.get('id', '')
            
            # Processar runners para obter status e possivelmente placar
            runners = market.get('runners', [])
            for runner in runners:
                runner_info = {
                    'selection_id': runner.get('id'),
                    'status': runner.get('status'),
                    'last_price_traded': runner.get('ltp'),
                }
                
                # Se o mercado está CLOSED, o runner pode ter resultado
                if market_status == 'CLOSED':
                    runner_info['settled'] = True
                    # Tentar determinar se ganhou ou perdeu baseado no status
                    if runner.get('status') == 'WINNER':
                        runner_info['result'] = 'WIN'
                    elif runner.get('status') == 'LOSER':
                        runner_info['result'] = 'LOSE'
                    else:
                        runner_info['result'] = 'PLACE'
                
                result['runners'].append(runner_info)
            
            return result
            
        except Exception as e:
            logging.getLogger(__name__).error(f"Erro ao buscar resultado do mercado: {e}")
            return None


def main():
    """Exemplo de uso da API"""
    print("=== Exemplo de Uso da API Betfair ===\n")
    
    try:
        # Criar cliente
        api = BetfairAPI()
        
        # Fazer login
        print("1. Fazendo login...")
        if not api.login():
            print("✗ Falha no login")
            return
        
        print("✓ Login realizado com sucesso\n")
        
        # Obter fundos da conta
        print("2. Obtendo fundos da conta...")
        funds = api.get_account_funds()
        print(f"✓ Fundos disponíveis: {funds.get('availableToBetBalance', 'N/A')}\n")
        
        # Listar tipos de eventos
        print("3. Listando tipos de eventos...")
        event_types = api.list_event_types()
        print(f"✓ Encontrados {len(event_types)} tipos de eventos")
        for event_type in event_types[:5]:  # Mostrar apenas os 5 primeiros
            print(f"  - {event_type.get('eventType', {}).get('name', 'N/A')}")
        
    except Exception as e:
        print(f"✗ Erro: {e}")


if __name__ == '__main__':
    main()
