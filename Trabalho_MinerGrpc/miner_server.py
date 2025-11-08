import grpc
from concurrent import futures
import time
import random
import hashlib
import threading

# Importe as classes geradas
import miner_pb2
import miner_pb2_grpc

class MinerServicer(miner_pb2_grpc.MinerServicer):
    """
    Implementação do serviço gRPC Miner.
    """
    def __init__(self):
        # A "tabela" de transações
        # Formato: { txID: {"challenge": N, "solution": "...", "winner": clientID} }
        self.transactions = {}
        self.current_transaction_id = -1
        # Trava para proteger o acesso concorrente à tabela de transações
        self.lock = threading.Lock()
        
        # (a) Gerar o primeiro desafio ao carregar
        self._generate_new_challenge()

    def _generate_new_challenge(self):
        """
        Função auxiliar interna para criar um novo desafio.
        DEVE ser chamada dentro de um 'with self.lock:'
        """
        self.current_transaction_id += 1
        tx_id = self.current_transaction_id
        
        # (b) Gera desafios aleatórios [1..20]
        # Mude para um desafio mais razoável
        challenge = random.randint(1, 20)
        
        # (a) Adiciona à tabela
        self.transactions[tx_id] = {
            "challenge": challenge,
            "solution": None,
            "winner": -1  # (d) -1 significa que não foi solucionado
        }
        print(f"[Servidor] Novo desafio gerado para TransactionID {tx_id} (Challenge: {challenge})")

    def _check_solution(self, challenge, solution):
        """
        Verifica se a 'solution' resolve o 'challenge'.
        O desafio N é resolvido se o hash SHA-1 da solução começar com N zeros.
        """
        if not solution:
            return False
            
        try:
            # Calcula o hash SHA-1 da solução
            hash_hex = hashlib.sha1(solution.encode('utf-8')).hexdigest()
            
            # O "desafio" é o número de zeros à esquerda necessários
            target_prefix = '0' * challenge
            
            return hash_hex.startswith(target_prefix)
        except Exception as e:
            print(f"[Servidor] Erro ao verificar solução: {e}")
            return False

    # --- Implementação dos Métodos RPC ---

    def getTransactionID(self, request, context):
        """
        Retorna o valor atual da transação com desafio ainda pendente.
        """
        with self.lock:
            tx_id = self.current_transaction_id
        
        return miner_pb2.TransactionIDResponse(transactionID=tx_id)

    def getChallenge(self, request, context):
        """
        Se transactionID for válido, retorne o valor do desafio associado a ele.
        Retorne -1 se o transactionID for inválido.
        """
        tx_id = request.transactionID
        challenge = -1
        
        with self.lock:
            if tx_id in self.transactions:
                challenge = self.transactions[tx_id]["challenge"]
                
        return miner_pb2.ChallengeResponse(challenge=challenge)

    def getTransactionStatus(self, request, context):
        """
        Se transactionID for válido, retorne:
        0 se o desafio já foi resolvido.
        1 se a transação ainda possui desafio pendente.
        -1 se a transactionID for inválida.
        """
        tx_id = request.transactionID
        status = -1  # Padrão: inválido

        with self.lock:
            if tx_id in self.transactions:
                if self.transactions[tx_id]["winner"] == -1:
                    status = 1  # Pendente
                else:
                    status = 0  # Resolvido
                    
        return miner_pb2.StatusResponse(status=status)

    def submitChallenge(self, request, context):
        """
        Submete uma solução para a referida transactionID.
        Retorne 1 se a solução for válida.
        Retorne 0 se for inválida.
        Retorne 2 se o desafio já foi solucionado.
        Retorne -1 se a transactionID for inválida.
        """
        tx_id = request.transactionID
        client_id = request.clientID
        solution = request.solution
        
        result = -1 # Padrão: inválido

        with self.lock:
            # 1. Checa se a TX é válida
            if tx_id not in self.transactions:
                result = -1
            # 2. Checa se já foi solucionado
            elif self.transactions[tx_id]["winner"] != -1:
                result = 2
            else:
                # 3. Se está pendente, verifica a solução
                challenge = self.transactions[tx_id]["challenge"]
                is_valid = self._check_solution(challenge, solution)
                
                if is_valid:
                    # Solução correta!
                    result = 1
                    self.transactions[tx_id]["solution"] = solution
                    self.transactions[tx_id]["winner"] = client_id
                    print(f"[Servidor] Solução ACEITA para TX {tx_id} do Cliente {client_id}")
                    
                    # Gera o próximo desafio
                    self._generate_new_challenge()
                else:
                    # Solução incorreta
                    result = 0
                    print(f"[Servidor] Solução RECUSADA para TX {tx_id} do Cliente {client_id}")

        return miner_pb2.SubmitResponse(result=result)

    def getWinner(self, request, context):
        """
        Retorna o clientID do vencedor da transação.
        Retorne 0 se transactionID ainda não tem vencedor.
        Retorne -1 se transactionID for inválida.
        """
        tx_id = request.transactionID
        winner_id = -1 # Padrão: inválido

        with self.lock:
            if tx_id in self.transactions:
                if self.transactions[tx_id]["winner"] == -1:
                    winner_id = 0  # Sem vencedor ainda
                else:
                    winner_id = self.transactions[tx_id]["winner"]
                    
        return miner_pb2.WinnerResponse(winnerID=winner_id)

    def getSolution(self, request, context):
        """
        Retorna uma estrutura com o status, a solução e o desafio.
        """
        tx_id = request.transactionID
        status = -1
        solution = ""
        challenge = -1
        
        with self.lock:
            if tx_id in self.transactions:
                tx_data = self.transactions[tx_id]
                challenge = tx_data["challenge"]
                
                if tx_data["winner"] == -1:
                    status = 1  # Pendente
                else:
                    status = 0  # Resolvido
                    solution = tx_data["solution"]
            
            # Se tx_id não estava em self.transactions, os valores padrão (-1, "", -1) serão usados
            
        return miner_pb2.SolutionInfoResponse(
            status=status, 
            solution=solution, 
            challenge=challenge
        )

# --- Função Principal para Iniciar o Servidor ---

def serve():
    """
    Inicia o servidor gRPC e aguarda conexões.
    """
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    miner_pb2_grpc.add_MinerServicer_to_server(MinerServicer(), server)
    
    port = "50051"
    server.add_insecure_port(f"[::]:{port}")
    
    print(f"--- Servidor Minerador gRPC iniciado na porta {port} ---")
    
    server.start()
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        print("Servidor interrompido.")
        server.stop(0)

if __name__ == "__main__":
    serve()