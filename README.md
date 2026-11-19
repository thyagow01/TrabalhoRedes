# Jogo da Forca

Trabalho de Redes — Departamento de Ciência da Computação (CIC), Universidade de Brasília (UnB)  

---

## Integrantes do Grupo

| Nome | Matrícula |
|---|:---:|
| **Eduardo Kachel Pereira** | 241009780 |
| **João Pedro Martins França** | 241009815 |
| **Thiago Rocha Gomes Urbano** | 241040646 |

---

## Descrição do Trabalho

O jogo da forca foi implementado usando um server rendezvous disponibilizado pelo professor em que nos usamos como ponto de encontro e conectamos nos peers trocando mensagems para jogar a forca.

Cada peer na rede atua como cliente e host:
- Descoberta: Os nos utilizam o server RDV para se registrar, descobrir outros peers e sair do server.
- TCP: Conexões TCP são estabelecidas entre todos os nós possiveis
- Keepalive e RTT: As conexoes são monitoradas com pacotes `PING`/`PONG` a cada 30 segundos com timestamps em padrão ISO 8601 UTC(bot do server exige isso), calculando a latência média (RTT) e detectando inativos após 3 falhas em responder o ping.

---

## Como rodar

Execute o arquivo principal:
```bash
python main.py
```
Se nenhum argumento for fornecido, o programa vai pedir o Nome, namespace e porta, sugerindo como padrão os valores presentes no `config.json` e se não colocar nada ele usa eles mesmos.

Você pode passar os parâmetros diretamente via terminal:
```bash
python main.py <nome> <namespace> <porta>
```
O arquivo `config.json` na raiz permite personalizar os parâmetros:
```json
{
  "rdv_host": "pyp2p.mfcaetano.cc",
  "rdv_port": 8080,
  "namespace": "CIC",
  "name": "joao",
  "listen_port": 9001,
  "register_ttl": 7200,
  "discover_interval": 20,
  "ping_interval": 30,
  "ping_miss_limit": 3,
  "max_reconnect_attempts": 5,
  "base_backoff": 2,
  "max_backoff": 60,
  "lives": 6,
  "max_players": 4,
  "turn_timeout": 30,
  "words_file": "words.txt",
  "log_file": null
}
```

---

## Comandos da Interface (CLI)

Dentro do terminal voce pode dar um /help e encontrar todos os comandos possiveis para o jogo e gerir conexoes conexoes

| Comando | Descrição |
|---|---|
| `/peers` | Lista os peers registrados no servidor Rendezvous |
| `/conn` | Exibe as conexões TCP ativas (direção INBOUND/OUTBOUND, porta e RTT) |
| `/rtt` | Exibe o RTT médio para cada peer |
| `/reconnect` | Força um novo ciclo no RDV |
| `/games` | mostra lista dos jogos disponives |
| `/create <palavra> [max]` | Cria uma sala com uma palavra específica |
| `/create --random [max]` | Cria uma sala sorteando palavra do `words.txt` |
| `/start` | Inicia a partida (host) |
| `/cancel` | Cancela a partida (Host) |
| `/join <host_id>` | Entra na sala do peer com o esse id |
| `/leave` | Quita da partida |
| `/guess <letra>` | Chuta a letra |
| `/word <palavra>` | Chuta a palavra |
| `/status` | exibe o status da partida |
| `/log <nível>` | Altera o nível de log (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `/help` | Exibe o menu de ajuda com os comandos |
| `/quit` | Quit fomral: sai do jogo, envia `BYE` aos peers e desregistra do RDV |

---

## Arquivos

O projeto está dividido de forma da maneira que foi sugerido nas especificações:

- **`main.py`**: Ponto de entrada do sistema. Inicializa o peer, carrega configurações, instancia os subsistemas e executa o loop da interface de linha de comando (CLI).
- **`rendezvous_connection.py`**: Cliente de comunicação com o servidor Rendezvous via TCP com timeout e validação de resposta.
- **`peer_connection.py`**: Gerenciador de conexões P2P. Implementa servidor e cliente TCP, handshake `HELLO`/`HELLO_OK`.
- **`peer_table.py`**: Tabela de roteamento e estados dos peers. Gerencia histórico de RTT e backoff exponencial para reconexões.
- **`keep_alive.py`**: Envia `PING` a cada 30 segundos, processa `PONG`, calcula RTT preciso e detecta falhas após 3 pings perdidos.
- **`game_host.py`**: Máquina de estados do Host (`IDLE`, `OPEN`, `RUNNING`, `FINISHED`). Controla lobby, turnos, expiração de tempo por jogada, validação de palpites e difusão de `STATE`..
- **`game_player.py`**: Máquina de estados do Jogador (`IDLE`, `JOINED`, `PLAYING`). Processa mensagens do Host, descarta estados fora de ordem por número de sequência (`seq`), forca em ASCII e valida o `word_hash`.
- **`hangman.py`**: Módulo da lógica do jogo da forca.
- **`json_handler.py`**: Utilitário de parsing, validação de mensagens e tratamento de erros do protocolo conforme a especificação.
- **`words.txt`**: Lista de palavras para o jogo randomico.

