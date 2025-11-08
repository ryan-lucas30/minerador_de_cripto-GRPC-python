import grpc
import sys
import random
import string
import hashlib
import threading

# Importe as classes geradas
import miner_pb2
import miner_pb2_grpc

# ID único para este cliente (poderia ser um argumento de linha de comando)
MY_CLIENT_ID = random.randint(1000, 9999)

# --- Funções de Mineração (Multi-thread) ---

# Objeto para sinalizar a todas as threads que uma solução foi encontrada
solution_found_event = threading.Event()
# Trava para proteger o armazenamento da solução
solution_lock = threading.Lock()
# Armazenamento para a solução encontrada
solution_storage = {"solution": None}

def mine_worker(challenge, target_prefix):
    """
    Função executada por cada thread de mineração.
    """
    global solution_storage, solution_found_event, solution_lock
    
    print(f"[Thread {threading.current_thread().name}] Iniciando... buscando prefixo {target_prefix}")
    
    while not solution_found_event.is_set():
        # Gera uma string aleatória (nonce)
        # Um contador incremental seria mais eficiente, mas isso simula a busca
        nonce = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
        
        # Calcula o hash
        hash_hex = hashlib.sha1(nonce.encode('utf-8')).hexdigest()
        
        # Verifica se encontrou a solução
        if hash_hex.startswith(target_prefix):
            # Trava para garantir que apenas uma thread salve a solução
            with solution_lock:
                # Verifica novamente caso outra thread tenha encontrado
                if not solution_found_event.is_set():
                    solution_storage["solution"] = nonce
                    solution_found_event.set() # Sinaliza para todas as outras pararem
                    print(f"\n[Thread {threading.current_thread().name}] SOLUÇÃO ENCONTRADA: {nonce}")
            return # Encerra esta thread

def local_mine(challenge):
    """
    Inicia o processo de mineração local com múltiplas threads.
    """
    global solution_storage, solution_found_event
    
    if challenge <= 0 or challenge > 20:
        print("Desafio inválido.")
        return None
        
    # Limpa eventos e armazenamento anteriores
    solution_found_event.clear()
    solution_storage["solution"] = None
    
    target_prefix = '0' * challenge
    num_threads = 8 # Número de threads (sugestão: use os.cpu_count())
    threads = []
    
    print(f"\nIniciando mineração local para desafio {challenge} (prefixo: {target_prefix}) com {num_threads} threads...")
    
    for i in range(num_threads):
        t = threading.Thread(target=mine_worker, args=(challenge, target_prefix), name=f"T-{i}")
        threads.append(t)
        t.start()
        
    # Espera até que o evento solution_found_event seja definido
    solution_found_event.wait()
    
    # Espera todas as threads terminarem (elas vão parar por causa do evento)
    for t in threads:
        t.join()
        
    return solution_storage["solution"]

# --- Funções do Menu (Chamadas RPC) ---

def get_input_txid():
    try:
        tx_id = int(input("Digite o TransactionID: "))
        return tx_id
    except ValueError:
        print("Entrada inválida. Por favor, digite um número.")
        return None

def do_get_transaction_id(stub):
    print("\n[1. getTransactionID]")
    response = stub.getTransactionID(miner_pb2.Empty())
    print(f"TransactionID atual (pendente): {response.transactionID}")

def do_get_challenge(stub):
    print("\n[2. getChallenge]")
    tx_id = get_input_txid()
    if tx_id is None: return
    
    request = miner_pb2.TransactionIDRequest(transactionID=tx_id)
    response = stub.getChallenge(request)
    if response.challenge == -1:
        print(f"TransactionID {tx_id} é inválido.")
    else:
        print(f"Desafio para TX {tx_id}: {response.challenge} (zeros)")

def do_get_transaction_status(stub):
    print("\n[3. getTransactionStatus]")
    tx_id = get_input_txid()
    if tx_id is None: return
    
    request = miner_pb2.TransactionIDRequest(transactionID=tx_id)
    response = stub.getTransactionStatus(request)
    if response.status == -1:
        print(f"TransactionID {tx_id} é inválido.")
    elif response.status == 0:
        print(f"Status da TX {tx_id}: 0 (Resolvido)")
    elif response.status == 1:
        print(f"Status da TX {tx_id}: 1 (Pendente)")

def do_get_winner(stub):
    print("\n[4. getWinner]")
    tx_id = get_input_txid()
    if tx_id is None: return
    
    request = miner_pb2.TransactionIDRequest(transactionID=tx_id)
    response = stub.getWinner(request)
    if response.winnerID == -1:
        print(f"TransactionID {tx_id} é inválido.")
    elif response.winnerID == 0:
        print(f"TX {tx_id} ainda não tem vencedor.")
    else:
        print(f"Vencedor da TX {tx_id}: Cliente {response.winnerID}")

def do_get_solution(stub):
    print("\n[5. getSolution]")
    tx_id = get_input_txid()
    if tx_id is None: return
    
    request = miner_pb2.TransactionIDRequest(transactionID=tx_id)
    response = stub.getSolution(request)
    
    if response.status == -1:
        print(f"TransactionID {tx_id} é inválido.")
    else:
        print(f"--- Detalhes da TX {tx_id} ---")
        print(f"Status: {'Pendente' if response.status == 1 else 'Resolvido'}")
        print(f"Desafio: {response.challenge}")
        print(f"Solução: {response.solution if response.solution else '(N/A)'}")

def do_mine(stub):
    """
    Executa o processo de mineração completo em 6 passos.
    """
    print("\n[6. Mine]")
    try:
        # 1. Buscar transactionID atual
        print("Passo 1: Buscando TransactionID atual...")
        tx_response = stub.getTransactionID(miner_pb2.Empty())
        tx_id = tx_response.transactionID
        print(f"   -> TransactionID atual: {tx_id}")
        
        # 2. Buscar a challenge (desafio)
        print(f"Passo 2: Buscando desafio para TX {tx_id}...")
        challenge_response = stub.getChallenge(miner_pb2.TransactionIDRequest(transactionID=tx_id))
        challenge = challenge_response.challenge
        
        if challenge == -1:
            print("   -> Erro: TransactionID inválida ou já resolvida no momento da busca.")
            return
        print(f"   -> Desafio: {challenge}")

        # 3. Buscar, localmente, uma solução (multi-thread)
        print("Passo 3: Iniciando mineração local (multi-thread)...")
        solution = local_mine(challenge)
        
        if not solution:
            print("   -> Erro: Mineração falhou.")
            return

        # 4. Imprimir localmente a solução encontrada
        print(f"Passo 4: Solução encontrada localmente: {solution}")

        # 5. Submeter a solução ao servidor
        print(f"Passo 5: Submetendo solução ao servidor (ClientID: {MY_CLIENT_ID})...")
        submit_request = miner_pb2.SolutionRequest(
            transactionID=tx_id,
            clientID=MY_CLIENT_ID,
            solution=solution
        )
        submit_response = stub.submitChallenge(submit_request)
        
        # 6. Imprimir/Decodificar resposta do servidor
        print("Passo 6: Resposta do Servidor:")
        result = submit_response.result
        if result == 1:
            print("   -> (1) SUCESSO! Solução aceita! Você venceu a TX!")
        elif result == 0:
            print("   -> (0) FALHA. Solução inválida.")
        elif result == 2:
            print("   -> (2) TARDE DEMAIS. Outro cliente resolveu primeiro.")
        elif result == -1:
            print("   -> (-1) ERRO. TransactionID tornou-se inválida.")
            
    except grpc.RpcError as e:
        print(f"Erro de RPC durante a mineração: {e.details()}")
    except Exception as e:
        print(f"Erro inesperado: {e}")


def print_menu():
    print("\n" + "=" * 30)
    print(f"Cliente Minerador (ID: {MY_CLIENT_ID})")
    print("=" * 30)
    print("1. getTransactionID (Ver TX atual)")
    print("2. getChallenge (Ver desafio p/ TX)")
    print("3. getTransactionStatus (Ver status da TX)")
    print("4. getWinner (Ver vencedor da TX)")
    print("5. getSolution (Ver detalhes da TX)")
    print("6. Mine (Tentar resolver o desafio atual)")
    print("0. Sair")
    print("-" * 30)
    return input("Escolha uma opção: ")

def run(server_address):
    """
    Função principal do cliente: conecta e exibe o menu.
    """
    print(f"Conectando ao servidor em {server_address}...")
    
    # 'with' garante que o canal seja fechado ao sair
    with grpc.insecure_channel(server_address) as channel:
        stub = miner_pb2_grpc.MinerStub(channel)
        
        # Verifica a conexão (opcional, mas bom)
        try:
            stub.getTransactionID(miner_pb2.Empty(), timeout=2)
            print("Conectado com sucesso!")
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.UNAVAILABLE:
                print(f"Erro: Não foi possível conectar ao servidor em {server_address}.")
                print("Verifique se o servidor está em execução.")
                return
            else:
                print(f"Erro de gRPC ao conectar: {e}")
                return

        # Loop do Menu
        while True:
            try:
                choice = print_menu()
                
                if choice == '1':
                    do_get_transaction_id(stub)
                elif choice == '2':
                    do_get_challenge(stub)
                elif choice == '3':
                    do_get_transaction_status(stub)
                elif choice == '4':
                    do_get_winner(stub)
                elif choice == '5':
                    do_get_solution(stub)
                elif choice == '6':
                    do_mine(stub)
                elif choice == '0':
                    print("Saindo...")
                    break
                else:
                    print("Opção inválida.")
                    
            except grpc.RpcError as e:
                print(f"\n[ERRO DE COMUNICAÇÃO RPC]")
                print(f"   Detalhes: {e.details()} (Código: {e.code().name})")
                print("   O servidor pode ter sido desconectado. Tentando reconectar...")
                # Tenta reconectar ou sai
                try:
                    # Tenta uma chamada simples para ver se o servidor voltou
                    stub.getTransactionID(miner_pb2.Empty(), timeout=2)
                    print("   Reconectado!")
                except grpc.RpcError:
                    print("   Falha ao reconectar. Saindo.")
                    break
            except KeyboardInterrupt:
                print("\nSaindo...")
                break

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python miner_client.py <endereco_servidor:porta>")
        print("Exemplo: python miner_client.py localhost:50051")
        sys.exit(1)
        
    server_addr = sys.argv[1]
    run(server_addr)