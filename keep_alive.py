######################################
#Eduardo Kachel Pereira: 241009780   #
#João Pedro Martins França: 241009815#
#Thiago Rocha Gomes Urbano: 241040646#
######################################
import time
import uuid
import logging
import threading
from datetime import datetime, timezone

log = logging.getLogger("keep_alive")

def timestamputc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") #so pra colocar no formato que o bot aceita

def criar_ping():
    return { #cria a msg de ping q manda
        "type": "PING",
        "msg_id": str(uuid.uuid4()),
        "ttl": 1,
        "timestamp": timestamputc(),
    }

def criar_pong(timestamp_original):
    return { #cria resposta do ping
        "type": "PONG",
        "msg_id": str(uuid.uuid4()),
        "ttl": 1,
        "timestamp": str(timestamp_original),
    }

class KeepAlive:
    def __init__(self, ger_conex, peer_table, intervalo=30):
        self.ger_conex = ger_conex
        self.peer_table = peer_table
        self.intervalo = intervalo
        self.ping_tempo = {}

        self.falhas = {}
        self.lock = threading.RLock()

        self.rodando = False
        self.thread = None
        return

    def iniciar(self):
        self.rodando = True
        self.thread = threading.Thread(target=self.loop_keepalive, daemon=True)
        self.thread.start()
        log.info(f"[KeepAlive] Iniciado com intervalo: {self.intervalo}s")
        return

    def parar(self):
        self.rodando = False
        log.info("[KeepAlive] Parado")
        return

    def loop_keepalive(self):
        while self.rodando:
            time.sleep(self.intervalo) #espera o intervalo estabelecido
            if self.rodando:  #se tiver rodando ainda da o ping
                self.enviar_ping()
        return

    def enviar_ping(self):
        conect = self.peer_table.list_conect() #pega a lista dos peers conectados

        for peer_id in conect: #passa por todos mandando ping
            with self.lock:
                erros = self.falhas.get(peer_id, 0) #ve se tem falha

                if erros >= 3: #se tiver 3 ou mais deu timeout e desconecta e gone
                    log.warning(f"[KeepAlive] {peer_id} Perdeu 3 pings seguidos -> Desconctando")
                    self.falhas.pop(peer_id, None)
                    self.ger_conex.desconectar(peer_id, motivo="Timeout de 3 pings")
                    continue
                self.falhas[peer_id] = erros+1

            self.ping_tempo[peer_id] = time.time() #pega a hora pra calcular o rtt dps
            self.ger_conex.enviar(peer_id, criar_ping())
            log.debug(f"[KeepAlive] Ping para {peer_id} enviado (esperando pong {self.falhas[peer_id]})")
        return

    def tratar_msg(self, peer_id, msg):
        tipo = msg.get("type")

        if tipo == "PING": #ve se é ping se for manda pong
            ts = msg.get("timestamp")
            self.ger_conex.enviar(peer_id, criar_pong(ts))
            log.debug(f"[KeepAlive] Pong respondido para {peer_id}")
            return True
        elif tipo == "PONG": #ve se é pong calcula o rtt
            with self.lock:
                self.falhas[peer_id] = 0
            try:
                if peer_id in self.ping_tempo:
                    rtt_ms = (time.time()-self.ping_tempo.pop(peer_id))*1000 #pega o tempo e dps faz vira ms
                    self.peer_table.calc_rtt(peer_id, rtt_ms)
            except Exception as e:
                log.warning(f"[KeepAlive] Erro no RTT de {peer_id}: {e}")

            return True
        return False