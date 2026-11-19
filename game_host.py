######################################
#Eduardo Kachel Pereira: 241009780   #
#João Pedro Martins França: 241009815#
#Thiago Rocha Gomes Urbano: 241040646#
######################################
import logging
import threading
import time
import uuid
from datetime import datetime, timezone

from hangman import JogoDaForca, sortear_palavra

log = logging.getLogger("game_host")

# maquina de estados do host
IDLE = "IDLE"
OPEN = "OPEN"
RUNNING = "RUNNING"
FINISHED = "FINISHED"


def _timestamp_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class GameHost:
    def __init__(self,meu_peer_id,ger_conex,vidas_padrao=6,max_players_padrao=4,turn_timeout=30,arquivo_palavras="words.txt",esta_jogando=None):
        self.meu_peer_id = meu_peer_id
        self.ger_conex = ger_conex
        self.vidas_padrao = int(vidas_padrao)
        self.max_players_padrao = int(max_players_padrao)
        self.turn_timeout = int(turn_timeout)
        self.arquivo_palavras = arquivo_palavras

        self.esta_jogando = esta_jogando or (lambda: False)    

        self.lock = threading.RLock()

        self._timer_turno = None
        self._timer_finished = None

        self._resetar_estado()

    def _resetar_estado(self):
        self._cancelar_timer_turno()
        self._cancelar_timer_finished()

        self.estado = IDLE
        self.game_id = None
        self.jogo = None
        self.max_players = self.max_players_padrao
        self.players = []
        self.participantes_historico = set()  #p/ rejoin
        self.scores = {}
        self.indice_turno = 0
        self.seq = 0
        self.inicio_turno_ts = None

    def tem_partida_ativa(self):      #autoexplicativo
        with self.lock:
            if self.estado == OPEN or self.estado == RUNNING:
                return True
            else:
                return False
 
    def _criar_envelope(self, tipo, dst, campos_extras=None, ref_msg_id=None):         #cabecalho base + campos extras(opcional) das mensagens
        msg = {
            "type": tipo,
            "msg_id": ref_msg_id if ref_msg_id else str(uuid.uuid4()),
            "ttl": 1,
            "src": self.meu_peer_id,
            "dst": dst,
            "timestamp": _timestamp_utc(),
        }
        if campos_extras:
            msg.update(campos_extras)
        return msg


        #---timers---

    #timers de turno pros jogador jogar(30sec)
    def _cancelar_timer_turno(self):
        if self._timer_turno:
            self._timer_turno.cancel()
            self._timer_turno = None

    def _iniciar_timer_turno(self):
        self._cancelar_timer_turno()
        if self.estado != RUNNING or not self.players:
            return
        self.inicio_turno_ts = time.monotonic()
        jogador_da_vez = self.players[self.indice_turno]
        self._timer_turno = threading.Timer(self.turn_timeout, self._on_timeout_turno, args=(self.game_id, self.seq, jogador_da_vez))
        self._timer_turno.daemon = True
        self._timer_turno.start()

    def _cancelar_timer_finished(self):
        if self._timer_finished:
            self._timer_finished.cancel()
            self._timer_finished = None

    #segundo o doc do projeto, a partida fica FINISHED por 60 segundos e depois reseta
    def _agendar_limpeza_finished(self):       
        self._cancelar_timer_finished()
        gid = self.game_id
        self._timer_finished = threading.Timer(60.0, self._on_fim_periodo_finished, args=(gid,))
        self._timer_finished.daemon = True
        self._timer_finished.start()

    def _on_fim_periodo_finished(self, gid):
        with self.lock:
            if self.estado == FINISHED and self.game_id == gid:
                log.info(f"[Host] Período FINISHED encerrado para {gid} -> IDLE")
                self._resetar_estado()


    #---comandos do host---


    def criar_partida(self, palavra=None, aleatoria=False, max_players=None):  #/create -- tem parametros opcionais p escolher a palavra ou aleatoria
        with self.lock:
            if self.estado in (OPEN, RUNNING):
                raise RuntimeError(f"Já existe uma partida ativa ({self.game_id}). Cancele-a antes (/cancel).")
            if self.esta_jogando():
                raise RuntimeError("Você já está participando de uma partida como jogador (/leave antes).")

            if self.estado == FINISHED:  #ignora o timer do finished
                self._resetar_estado()

            if aleatoria:
                palavra_escolhida = sortear_palavra(self.arquivo_palavras)
            else:
                if not palavra:
                    raise ValueError("Informe uma palavra ou use --random.")
                palavra_escolhida = palavra

            self.jogo = JogoDaForca(palavra_escolhida, vidas=self.vidas_padrao)
            if max_players != None:
                self.max_players = int(max_players)
            else:
                self.max_players = self.max_players_padrao
            if self.max_players < 1:
                raise ValueError("max_players deve ser pelo menos 1.")

            self.game_id = f"{self.meu_peer_id}/{uuid.uuid4().hex[:8]}"
            self.estado = OPEN
            self.players = []
            self.participantes_historico = set()
            self.scores = {}
            self.indice_turno = 0
            self.seq = 0

            log.info(
                f"[Host] Game {self.game_id} created "
                f"(word_length={len(self.jogo.palavra_secreta)}, lives={self.vidas_padrao})"
            )
            return self.game_id

    def iniciar_partida(self):          #/start, aciona o RUNNING e GAME_START com o seq = 1
        with self.lock:
            if self.estado != OPEN:
                raise RuntimeError("Nenhuma partida aberta no lobby para iniciar.")
            if len(self.players) < 1:
                raise RuntimeError("São necessários pelo menos 1 jogador para iniciar.")

            self.estado = RUNNING
            self.indice_turno = 0
            word_hash = self.jogo.obter_word_hash()
            word_len = len(self.jogo.palavra_secreta)

            for player_id in self.players:
                msg_start = self._criar_envelope("GAME_START",player_id,
                    {"game_id": self.game_id,
                        "players": list(self.players),
                        "lives": self.jogo.vidas_iniciais,
                        "word_length": word_len,
                        "word_hash": word_hash,
                        "turn_timeout": self.turn_timeout})
                self.ger_conex.enviar(player_id, msg_start)

            log.info(f"[Host] Partida {self.game_id} iniciada com {len(self.players)} jogador(es)")
            self._difundir_state(last_guess=None)
            self._iniciar_timer_turno()

    def cancelar_partida(self, motivo="host_shutdown"):   #/cancel
        with self.lock:
            if self.estado not in (OPEN, RUNNING):
                return False

            self._cancelar_timer_turno()
            gid = self.game_id
            jogadores_atuais = list(self.players)

            if self.estado == RUNNING and jogadores_atuais: #rodando a partida
                self._encerrar_partida(result="ABORTED", winner=None, reason=motivo)
            else:      #se tava so aberta
                for p in jogadores_atuais:
                    msg_over = self._criar_envelope("GAME_OVER",p,
                        {"game_id": gid,
                            "result": "ABORTED",
                            "word": self.jogo.palavra_secreta if self.jogo else "",
                            "winner": None,
                            "scores": dict(self.scores),
                            "reason": motivo})
                    self.ger_conex.enviar(p, msg_over)
                log.info(f"[Host] Partida {gid} cancelada ({motivo})")
                self._resetar_estado()
            return True


    #---entradas---


    def tratar_mensagem(self, peer_id, msg):  #age de acordo com o tipo da msg recebida
        tipo = msg.get("type")

        if tipo == "GAME_LIST":
            self._on_game_list(peer_id, msg)
        elif tipo == "JOIN":
            self._on_join(peer_id, msg)
        elif tipo == "LEAVE":
            self._on_leave(peer_id, msg)
        elif tipo == "GUESS":
            self._on_guess(peer_id, msg)

    def _on_game_list(self, peer_id, msg):        #resposta ao listar_jogos/_on_game_list_ok do player 
        ref_id = msg.get("msg_id")
        with self.lock:
            if self.estado == IDLE or not self.game_id: #se nao tem, retorna vazio
                games = []
            else:    #se tem, retorna os dados da sala
                games = [{"game_id": self.game_id,
                        "host": self.meu_peer_id,
                        "status": self.estado,
                        "players": list(self.players),
                        "max_players": self.max_players,
                        "lives": self.jogo.vidas_iniciais,
                        "word_length": len(self.jogo.palavra_secreta)}]

        resp = self._criar_envelope("GAME_LIST_OK", peer_id, {"games": games}, ref_msg_id=ref_id)
        self.ger_conex.enviar(peer_id, resp)

    def _on_join(self, peer_id, msg):      #/join do usuraio
        ref_id = msg.get("msg_id")
        req_game_id = msg.get("game_id", "")

        with self.lock:
            id_valido = (req_game_id == self.game_id or req_game_id in (self.meu_peer_id, f"{self.meu_peer_id}/default",""))
            if self.estado == IDLE or not id_valido:  #nem tem jogo
                self._enviar_join_error(peer_id, req_game_id, "unknown_game", ref_id)    
                return

            if self.estado == FINISHED:      #cabou jogo
                self._enviar_join_error(peer_id, self.game_id, "game_finished", ref_id)
                return

            if peer_id in self.players:      #ja ta no jogo
                self._enviar_join_error(peer_id, self.game_id, "already_joined", ref_id)
                return

            if len(self.players) >= self.max_players:   #ta cheio o jogo
                self._enviar_join_error(peer_id, self.game_id, "game_full", ref_id)
                return

            if peer_id == self.meu_peer_id:   #host entrando no proprio jogo
                self._enviar_join_error(peer_id, self.game_id, "host_cannot_join", ref_id)
                return

            if self.estado == RUNNING: #so aciona no caso de ser rejoin
                if peer_id not in self.participantes_historico:
                    self._enviar_join_error(peer_id, self.game_id, "game_running", ref_id)
                    return

                self.players.append(peer_id)
                self.scores.setdefault(peer_id, 0)
                resp = self._criar_envelope("JOIN_OK",peer_id,{"game_id": self.game_id, "players": list(self.players), "rejoin": True},ref_msg_id=ref_id)
                self.ger_conex.enviar(peer_id, resp)
                log.info(f"[Host] {peer_id} rejoined ({len(self.players)}/{self.max_players})")

                self._difundir_state(last_guess=None) #ja manda o STATE pro rejoin se atualizar
                return

            self.players.append(peer_id)  #entrada normal(OPEN)
            self.participantes_historico.add(peer_id)
            self.scores[peer_id] = 0

            resp = self._criar_envelope("JOIN_OK",peer_id,
                {"game_id": self.game_id, "players": list(self.players), "rejoin": False},
                ref_msg_id=ref_id)
            self.ger_conex.enviar(peer_id, resp)
            log.info(f"[Host] {peer_id} joined ({len(self.players)}/{self.max_players})")

    def _enviar_join_error(self, peer_id, game_id, reason, ref_msg_id): #erro ao entrar(auxilia o on_join)
        resp = self._criar_envelope("JOIN_ERR",peer_id,
            {"game_id": game_id, "reason": reason},
            ref_msg_id=ref_msg_id)
        self.ger_conex.enviar(peer_id, resp)

    def _on_leave(self, peer_id, msg):         #reage ao /leave
        ref_id = msg.get("msg_id")
        req_game_id = msg.get("game_id", "")

        with self.lock:
            resp = self._criar_envelope("LEAVE_OK", peer_id, {"game_id": req_game_id}, ref_msg_id=ref_id)    #da o OK 
            self.ger_conex.enviar(peer_id, resp)

            if self.estado in (OPEN, RUNNING) and req_game_id == self.game_id and peer_id in self.players:      #remove e avisa
                log.info(f"[Host] {peer_id} saiu da partida {self.game_id}")
                self._remover_jogador_ativo(peer_id)

    def _on_guess(self, peer_id, msg):       #reage ao /guess(ou /word)
        ref_id = msg.get("msg_id")
        req_game_id = msg.get("game_id", "")

        with self.lock:
            if self.estado != RUNNING or req_game_id != self.game_id:      #jogo nao ta rodando ainda
                self._enviar_guess_result(peer_id, req_game_id, accepted=False, reason="game_not_running", ref_id=ref_id)
                return

            if not self.players or self.players[self.indice_turno] != peer_id:       #nao é o turno do jogador ainda
                self._enviar_guess_result(peer_id, self.game_id, accepted=False, reason="not_your_turn", ref_id=ref_id)
                return

            tem_letter = "letter" in msg
            tem_word = "word" in msg

            if tem_letter == tem_word:  #só um pode ser true
                self._enviar_guess_result(peer_id, self.game_id, accepted=False, reason="invalid_letter", ref_id=ref_id)
                return

            try:
                if tem_letter:        #chute da letra
                    acertou, pontos = self.jogo.tentar_letra(msg["letter"])
                    jogada_info = {"player": peer_id, "letter": msg["letter"].strip().lower(), "correct": acertou}
                    log.info(
                        f"[Host] GUESS {peer_id} letter={jogada_info['letter']} → "
                        f"{'correct' if acertou else 'wrong'}, masked={self.jogo.obter_mascara()}"
                    )
                else:           #chute da palavra
                    acertou, pontos = self.jogo.tentar_palavra(msg["word"])
                    jogada_info = {"player": peer_id, "word": msg["word"].strip().lower(), "correct": acertou}
                    log.info(
                        f"[Host] GUESS {peer_id} word={jogada_info['word']} → {'correct' if acertou else 'wrong'}"
                    )
            except ValueError as e:
                #erros(letra usada, invalida etc)
                self._enviar_guess_result(peer_id, self.game_id, accepted=False, reason=str(e), ref_id=ref_id)
                return

            self._cancelar_timer_turno()
            self.scores[peer_id] = self.scores.get(peer_id, 0) + pontos
            self._enviar_guess_result(peer_id, self.game_id, accepted=True, correct=acertou, ref_id=ref_id)

            if self.jogo.verificar_vitoria():             # ve se ganhou
                self._encerrar_partida(result="WON", winner=peer_id)
                return

            if self.jogo.verificar_derrota():
                self._encerrar_partida(result="LOST", winner=None)
                return

            self.indice_turno = (self.indice_turno + 1) % len(self.players)     #nao acabou -> passa o turno
            self._difundir_state(last_guess=jogada_info)
            self._iniciar_timer_turno()

    def _enviar_guess_result(self, peer_id, game_id, accepted, correct=None, reason=None, ref_id=None):        #retorno do chute
        extras = {"game_id": game_id, "accepted": accepted}
        if accepted:
            extras["correct"] = bool(correct)
        else:
            extras["reason"] = reason
        resp = self._criar_envelope("GUESS_RESULT", peer_id, extras, ref_msg_id=ref_id)
        self.ger_conex.enviar(peer_id, resp)



    #---gestao---


    def _difundir_state(self, last_guess):       #incrementa o seq e avisa geral (STATE)
        self.seq += 1 
        turno_atual = self.players[self.indice_turno]
        log.info(f"[Host] Turn: {turno_atual} (seq={self.seq}, timeout {self.turn_timeout} s)")

        for player_id in self.players:
            msg_state = self._criar_envelope("STATE",player_id,
                {"game_id": self.game_id,
                    "seq": self.seq,
                    "masked": self.jogo.obter_mascara(),
                    "wrong_letters": list(self.jogo.letras_erradas),
                    "lives": self.jogo.vidas_restantes,
                    "turn": turno_atual,
                    "players": list(self.players),
                    "last_guess": last_guess})
            self.ger_conex.enviar(player_id, msg_state)

    def _on_timeout_turno(self, gid, seq_esperado, jogador_lento):    #demorou perdeu o turno
        with self.lock:
            if self.estado != RUNNING or self.game_id != gid or self.seq != seq_esperado:
                return
            if not self.players or self.players[self.indice_turno] != jogador_lento:
                return

            log.info(f"[Host] Turn timeout for {jogador_lento} — skipping")
            self.indice_turno = (self.indice_turno + 1) % len(self.players)
            self._difundir_state(last_guess={"player": jogador_lento, "timeout": True})
            self._iniciar_timer_turno()

    def on_peer_desconectado(self, peer_id):  #peer desconectado / STALE -> remove o cara
        with self.lock:
            if self.estado in (OPEN, RUNNING) and peer_id in self.players:
                log.warning(f"[Host] Player {peer_id} STALE — removed from game")
                self._remover_jogador_ativo(peer_id)

    def _remover_jogador_ativo(self, peer_id):       #/leave ou desconectado
        idx_removido = self.players.index(peer_id)
        era_vez_dele = (self.estado == RUNNING and idx_removido == self.indice_turno)
        self.players.remove(peer_id)

        if self.estado == OPEN:     #nao comecou ainda
            self.participantes_historico.discard(peer_id) #semrejoin
            return
 
        if not self.players:      #sobrou ninguem
            self._cancelar_timer_turno()
            log.info(f"[Host] Nenhum jogador restante em {self.game_id} -> ABORTED")
            self._encerrar_partida(result="ABORTED", winner=None, reason="no_players")
            return

        if idx_removido < self.indice_turno: #ajuste de turno
            self.indice_turno -= 1
        elif era_vez_dele:
            self._cancelar_timer_turno()
            self.indice_turno = self.indice_turno % len(self.players)
            self._difundir_state(last_guess=None)
            self._iniciar_timer_turno()
            return

        self._difundir_state(last_guess=None)

    def _encerrar_partida(self, result, winner, reason=None):       #finaliza a partida
        self._cancelar_timer_turno()
        self.estado = FINISHED

        extras = {
            "game_id": self.game_id,
            "result": result,
            "word": self.jogo.palavra_secreta,
            "winner": winner,
            "scores": dict(self.scores)}
        if reason:
            extras["reason"] = reason

        for player_id in self.players:
            msg_over = self._criar_envelope("GAME_OVER", player_id, extras)
            self.ger_conex.enviar(player_id, msg_over)

        log.info(f"[Host] Game {self.game_id} finished: {result} (winner={winner})")
        self._agendar_limpeza_finished()       #começa os 60 segundos do FINISHED


    #--- exibicao ---

    def obter_status_texto(self):    #reage ao /status
        with self.lock:
            if self.estado == IDLE:
                return "[Game] Nenhuma partida hospedada no momento."

            forca = self.jogo.desenho_forca()
            erradas = ", ".join(self.jogo.letras_erradas) if self.jogo.letras_erradas else "-"
            jogadores_txt = ", ".join(self.players) if self.players else "(nenhum)"

            if self.estado == OPEN:
                return (f"[Game] {self.game_id}  (host: {self.meu_peer_id} - você)  status: OPEN\n"
                    f"[Game] Palavra secreta: {self.jogo.palavra_secreta}     "
                    f"Jogadores ({len(self.players)}/{self.max_players}): {jogadores_txt}")

            if self.players:
                turno_txt = self.players[self.indice_turno]
            else:
                turno_txt = "-"
            restante_txt = ""
            if self.estado == RUNNING and self.inicio_turno_ts is not None:
                decorrido = time.monotonic() - self.inicio_turno_ts
                restante = max(0, int(self.turn_timeout - decorrido))
                restante_txt = f"  — {restante} s restantes"

            return (
                f"{forca}\n"
                f"[Game] {self.game_id}  (host: {self.meu_peer_id} - você)  status: {self.estado}\n"
                f"[Game] Palavra: {self.jogo.obter_estado_formatado()} (secreta: {self.jogo.palavra_secreta})     "
                f"Vidas: {self.jogo.vidas_restantes} / {self.jogo.vidas_iniciais}     Erradas: {erradas}\n"
                f"[Game] Jogadores: {jogadores_txt}   Vez de: {turno_txt}{restante_txt}")
