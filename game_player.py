import hashlib
import logging
import threading
import time
import uuid
from datetime import datetime, timezone

from hangman import JogoDaForca, normalizar, validar_palavra

log = logging.getLogger("game_player")

# maquina de estados do player
IDLE = "IDLE"
JOINED = "JOINED"
PLAYING = "PLAYING"


def _timestamp_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _desenhar_forca(vidas_restantes, vidas_iniciais):
    if vidas_iniciais <= 0:
        return JogoDaForca.ESTAGIOS_FORCA[0]
    erros = max(0, vidas_iniciais - vidas_restantes)
    max_idx = len(JogoDaForca.ESTAGIOS_FORCA) - 1
    indice = min(max_idx, round((erros / vidas_iniciais) * max_idx))
    return JogoDaForca.ESTAGIOS_FORCA[indice]


class GamePlayer:
    def __init__(self, meu_peer_id, ger_conex, peer_table, tem_jogo_host_fn=None):
        self.meu_peer_id = meu_peer_id     
        self.ger_conex = ger_conex
        self.peer_table = peer_table

        self.tem_jogo_host_fn = tem_jogo_host_fn or (lambda: False)   #checar se o peer é o host

        self.lock = threading.RLock()

        self.jogos_disponiveis = {}

        self._resetar_estado()

    def _resetar_estado(self):
        self.estado = IDLE
        self.host_peer_id = None
        self.game_id = None
        self.players = []
        self.vidas_iniciais = 6
        self.vidas_restantes = 6
        self.word_length = 0
        self.word_hash = None
        self.turn_timeout = 30
        self.ultimo_seq = 0
        self.masked = ""
        self.wrong_letters = []
        self.turn = None
        self.last_guess = None
        self.inicio_turno_ts = None
        self._join_pendente_msg_id = None
        self._leave_pendente_msg_id = None

    def esta_em_partida(self):
        with self.lock:
            return self.estado != IDLE

    def _criar_envelope(self, tipo, destino, campos_extras=None):      #define o cabeçalho padrao p troca de mensagens
        msg = {
            "type": tipo,
            "msg_id": str(uuid.uuid4()),
            "ttl": 1,
            "src": self.meu_peer_id,
            "dst": destino,
            "timestamp": _timestamp_utc(),
        }
        if campos_extras:
            msg.update(campos_extras)
        return msg


    #---saidas---


    def listar_jogos(self):        #envia GAME_LIST -> buscando GAME_LIST_OK, as partidas hospedadas
        with self.lock:
            self.jogos_disponiveis.clear()

        conectados = self.peer_table.list_conect()
        enviados = 0

        for peer_id in conectados:
            info = self.peer_table.obter_peer(peer_id)
            if not info:       #se o id for vazio, segue
                continue

            if "hangman" not in info.get("features", []):      #só envia p quem anuncia "hangman"
                continue

            msg = self._criar_envelope("GAME_LIST", peer_id)
            if self.ger_conex.enviar(peer_id, msg):
                enviados += 1

        log.info(f"[Player] GAME_LIST enviado para {enviados} vizinho(s)")
        return enviados

    def entrar_jogo(self, host_peer_id, game_id=None): #envia o JOIN
        with self.lock:
            if self.estado != IDLE:     #se nao ta no "lobby"(idle), nao pede pra entrar em outra sala
                raise RuntimeError(f"Você já está em uma partida ({self.game_id}). Saia antes (/leave).")
            if self.tem_jogo_host_fn():      #se é host, nao pede pra entrar em outra sala
                raise RuntimeError("Você já está hospedando uma partida. Cancele-a antes (/cancel).")

            if not game_id:
                jogos = self.jogos_disponiveis.get(host_peer_id)
                if not jogos:
                    raise ValueError(
                        f"Nenhuma partida conhecida para {host_peer_id}. Execute /games primeiro ou informe o game_id."
                    )
                game_id = jogos["game_id"]           #verifica a existência do game.id destino, da partida, tirando la do jogos_disponiveis()

            msg = self._criar_envelope("JOIN", host_peer_id, {"game_id": game_id})
            if not self.ger_conex.enviar(host_peer_id, msg):
                raise RuntimeError(f"Não foi possível enviar JOIN para {host_peer_id} (sem conexão ativa).")

            self._join_pendente_msg_id = msg["msg_id"]
            self.host_peer_id = host_peer_id
            self.game_id = game_id
            log.info(f"[Player] Solicitando entrada em {game_id}...")        #envia o join, sem alterar o tipo ainda(so com a msg do ok do host)

    def sair_jogo(self): #LEAVE, encerra a participação
        with self.lock:
            if self.estado == IDLE or not self.host_peer_id:    # nao da pra sair sem estar em uma partida
                raise RuntimeError("Você não está em nenhuma partida.") 

            host = self.host_peer_id
            gameid = self.game_id
            msg = self._criar_envelope("LEAVE", host, {"game_id": gameid})
            self.ger_conex.enviar(host, msg)
            log.info(f"[Player] Saiu da partida {gameid}")
            self._resetar_estado()

    def enviar_palpite_letra(self, letra): #mandar o GUESS de letra
        chave = normalizar(letra)
        if len(chave) != 1 or not ("a" <= chave <= "z"):
            raise ValueError("Palpite inválido: informe uma única letra de 'a' a 'z'.")

        with self.lock:
            self._validar_pronto_para_jogar()
            msg = self._criar_envelope("GUESS",self.host_peer_id,{"game_id": self.game_id, "letter": chave})
            if not self.ger_conex.enviar(self.host_peer_id, msg):
                raise RuntimeError("Falha ao enviar palpite: host desconectado.")
            log.info(f"[Player] Palpite de letra enviado: '{chave}'")

    def enviar_palpite_palavra(self, palavra): #mandar o GUESS de palavra
        palpite = validar_palavra(palavra)

        with self.lock:
            self._validar_pronto_para_jogar()
            msg = self._criar_envelope(
                "GUESS",
                self.host_peer_id,
                {"game_id": self.game_id, "word": palpite},
            )
            if not self.ger_conex.enviar(self.host_peer_id, msg):
                raise RuntimeError("Falha ao enviar palpite: host desconectado.")
            log.info(f"[Player] Palpite de palavra enviado: '{palpite}'")

    def _validar_pronto_para_jogar(self):
        if self.estado != PLAYING:
            raise RuntimeError("A partida ainda não está em andamento.")
        if self.turn != self.meu_peer_id:
            raise RuntimeError(f"Não é sua vez! Aguardando jogada de {self.turn}.")


    #---entradas---


    def tratar_mensagem(self, peer_id, msg):  #atualiza de acordo com a msg recebida do host
        tipo = msg.get("type")

        if tipo == "GAME_LIST_OK":
            self._on_game_list_ok(peer_id, msg)
        elif tipo == "JOIN_OK":
            self._on_join_ok(peer_id, msg)
        elif tipo == "JOIN_ERR":
            self._on_join_err(peer_id, msg)
        elif tipo == "LEAVE_OK":
            log.debug(f"[Player] LEAVE_OK recebido de {peer_id}")
        elif tipo == "GAME_START":
            self._on_game_start(peer_id, msg)
        elif tipo == "STATE":
            self._on_state(peer_id, msg)
        elif tipo == "GUESS_RESULT":
            self._on_guess_result(peer_id, msg)
        elif tipo == "GAME_OVER":
            self._on_game_over(peer_id, msg)
        elif tipo == "ERROR":
            self._on_error(peer_id, msg)

    # funcoes que atuam com base na msg recebida

    def _on_game_list_ok(self, peer_id, msg):   #rtorno da listar_jogos
        games = msg.get("games", [])
        with self.lock:
            for g in games:
                host = g.get("host", peer_id)
                self.jogos_disponiveis[host] = g
                status = g.get("status")
                gameid = g.get("game_id")
                qtd = len(g.get("players", []))
                max_p = g.get("max_players")
                w_len = g.get("word_length")
                lives = g.get("lives")
                print(f"[CLI]   {gameid}  host={host}  status={status}  {qtd}/{max_p} jogadores  {w_len} letras  {lives} vidas")

    def _on_join_ok(self, peer_id, msg):
        with self.lock:
            if peer_id != self.host_peer_id:   #roda em quase todas as funções de entrada, ve se o host que devolveu a msg
                return
            self.game_id = msg.get("game_id", self.game_id)
            self.players = list(msg.get("players", []))
            self._join_pendente_msg_id = None
            rejoin = msg.get("rejoin", False)

            if rejoin:                          #ve se caiu da sala(ja tava, saiu e entrou, ou se é novo)
                self.estado = PLAYING
                print(f"[Game] Reconectado à partida {self.game_id} (aguardando STATE...)")
            else:
                self.estado = JOINED
                print(f"[Game] Entrou no lobby {self.game_id}. Jogadores: {', '.join(self.players)}")

    def _on_join_err(self, peer_id, msg):
        with self.lock:
            if peer_id != self.host_peer_id:
                return
            reason = msg.get("reason", "unknown")
            gid = msg.get("game_id", self.game_id)
            print(f"[Game] Entrada recusada em {gid}: {reason}")
            self._resetar_estado()

    def _on_game_start(self, peer_id, msg):     
        with self.lock:
            if peer_id != self.host_peer_id or msg.get("game_id") != self.game_id:   #verifica se é o host certo e a partida certa
                return
            self.estado = PLAYING
            self.players = list(msg.get("players", []))
            self.vidas_iniciais = int(msg.get("lives", 6))
            self.vidas_restantes = self.vidas_iniciais
            self.word_length = int(msg.get("word_length", 0))
            self.word_hash = msg.get("word_hash")
            self.turn_timeout = int(msg.get("turn_timeout", 30))
            self.masked = "_" * self.word_length
            self.ultimo_seq = 0

            log.info(
                f"[Player] GAME_START {self.game_id}: {self.word_length} letras, "
                f"{self.vidas_iniciais} vidas, hash={self.word_hash}"
            )
            print(f"\n[Game] Partida {self.game_id} iniciada! Palavra com {self.word_length} letras.")

    def _on_state(self, peer_id, msg):      #sincroniza o cliente com as infos do jogo a cada STATE enviado do host
        with self.lock:
            if peer_id != self.host_peer_id or msg.get("game_id") != self.game_id:
                return

            seq = int(msg.get("seq", 0))            #usa o seq para impedir se atualizar com rodadas passadas, descartando ela nesse caso
            if seq <= self.ultimo_seq:
                log.debug(f"[Player] STATE seq={seq} ignored (already at seq={self.ultimo_seq})")
                return

            self.estado = PLAYING
            self.ultimo_seq = seq
            self.masked = msg.get("masked", self.masked)
            self.wrong_letters = list(msg.get("wrong_letters", []))
            self.vidas_restantes = int(msg.get("lives", self.vidas_restantes))
            self.turn = msg.get("turn")
            self.players = list(msg.get("players", self.players))
            self.last_guess = msg.get("last_guess")
            self.inicio_turno_ts = time.monotonic()

            sua_vez = " (você)" if self.turn == self.meu_peer_id else ""
            log.info(
                f"[Player] STATE seq={seq} applied: {self.masked} "
                f"lives={self.vidas_restantes} turn={self.turn}{sua_vez}"
            )

            if self.last_guess:
                jogador = self.last_guess.get("player")
                if self.last_guess.get("timeout"):
                    print(f"[Game] Tempo esgotado para {jogador} — turno passado.")
                elif "letter" in self.last_guess:
                    res = "acertou!" if self.last_guess.get("correct") else "errou."
                    print(f"[Game] {jogador} chutou letra '{self.last_guess['letter']}' → {res}")
                elif "word" in self.last_guess:
                    res = "ACERTOU!" if self.last_guess.get("correct") else "errou."
                    print(f"[Game] {jogador} arriscou palavra '{self.last_guess['word']}' → {res}")

            print(f"[Game] Palavra: {' '.join(self.masked)}  |  Vidas: {self.vidas_restantes}/{self.vidas_iniciais}  |  Vez de: {self.turn}{sua_vez}")

    def _on_guess_result(self, peer_id, msg):
        with self.lock:
            if peer_id != self.host_peer_id or msg.get("game_id") != self.game_id:
                return
            accepted = msg.get("accepted", False)
            if not accepted:
                reason = msg.get("reason", "unknown")
                log.warning(f"[Player] Palpite rejeitado pelo host: {reason}")
                print(f"[Game] Jogada rejeitada: {reason}")

    def _on_game_over(self, peer_id, msg):
        with self.lock:
            if peer_id != self.host_peer_id or msg.get("game_id") != self.game_id:
                return

            result = msg.get("result")
            word = msg.get("word", "")
            winner = msg.get("winner")
            scores = msg.get("scores", {})
            reason = msg.get("reason")

            # verifica se o hash foi alterado
            hash_status = "sem hash inicial"
            if self.word_hash and word:
                calculado = hashlib.sha256(word.encode("utf-8")).hexdigest()
                if calculado == self.word_hash:
                    hash_status = "hash OK"
                    log.info(f"[Player] GAME_OVER {result} word={word} winner={winner} — hash OK")
                else:
                    hash_status = "HASH MISMATCH!"
                    log.warning(f"[Player] host cheated: hash mismatch (esperado={self.word_hash}, recebido={calculado})")
            else:
                log.info(f"[Player] GAME_OVER {result} word={word} reason={reason}")

            print("\n==========================================")
            print(f"[Game] FIM DE JOGO — Resultado: {result}")
            if word:
                print(f"[Game] Palavra secreta: {word} ({hash_status})")
            if winner:
                print(f"[Game] Vencedor: {winner}")
            if reason:
                print(f"[Game] Motivo: {reason}")
            if scores:
                placar = ", ".join(f"{p}: {pts}" for p, pts in scores.items())
                print(f"[Game] Pontuação: {placar}")
            print("==========================================\n")

            self._resetar_estado()

    def _on_error(self, peer_id, msg):
        with self.lock:
            if peer_id == self.host_peer_id:
                log.warning(f"[Player] Erro recebido do host {peer_id}: {msg.get('code')} - {msg.get('message')}")
                if self._join_pendente_msg_id and msg.get("ref_msg_id") == self._join_pendente_msg_id:
                    self._resetar_estado()



    #---falhas---


    def on_peer_desconectado(self, peer_id):           #acionado quando o peer cai(STALE)
        with self.lock:
            if self.estado != IDLE and peer_id == self.host_peer_id:               #se o host cai, quita da sala
                log.warning(f"[Player] Host {peer_id} unreachable — game aborted")
                print(f"\n[Game] Host {peer_id} unreachable — game aborted")
                self._resetar_estado()

    def obter_status_texto(self):    #output pro /status do usuario
        with self.lock:
            if self.estado == IDLE:
                return "[Game] Nenhuma partida ativa como jogador."

            if self.estado == JOINED:
                return (
                    f"[Game] {self.game_id}  (host: {self.host_peer_id})  status: JOINED (aguardando início)\n"
                    f"[Game] Jogadores no lobby: {', '.join(self.players)}"
                )

            forca = _desenhar_forca(self.vidas_restantes, self.vidas_iniciais)
            erradas = ", ".join(self.wrong_letters) if self.wrong_letters else "-"
            sua_vez = " (você)" if self.turn == self.meu_peer_id else ""

            restante_txt = ""
            if self.inicio_turno_ts is not None:
                decorrido = time.monotonic() - self.inicio_turno_ts
                restante = max(0, int(self.turn_timeout - decorrido))
                restante_txt = f"  — {restante} s restantes"

            return (
                f"{forca}\n"
                f"[Game] {self.game_id}  (host: {self.host_peer_id})  status: RUNNING\n"
                f"[Game] Palavra: {' '.join(self.masked)}     "
                f"Vidas: {self.vidas_restantes} / {self.vidas_iniciais}     Erradas: {erradas}\n"
                f"[Game] Jogadores: {', '.join(self.players)}   "
                f"Vez de: {self.turn}{sua_vez}{restante_txt}"
            )