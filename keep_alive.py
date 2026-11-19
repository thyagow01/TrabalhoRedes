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

def criar_pong(timestamp_original, msg_id=None):
    return { #cria resposta do ping
        "type": "PONG",
        "msg_id": msg_id if msg_id else str(uuid.uuid4()),
        "ttl": 1,
        "timestamp": str(timestamp_original),
    }

class KeepAlive:
    def __init__(self, ger_conex, peer_table, intervalo=30, miss_limit=3):
        self.ger_conex = ger_conex
        self.peer_table = peer_table
        self.intervalo = int(intervalo)
        self.miss_limit = int(miss_limit)
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
            desconectar_peer = False
            ping_msg = criar_ping()
            with self.lock:
                erros = self.falhas.get(peer_id, 0) #ve se tem falha

                if erros >= self.miss_limit: #se atingiu o limite deu timeout e desconecta
                    self.falhas.pop(peer_id, None)
                    self.ping_tempo.pop(peer_id, None)
                    desconectar_peer = True
                else:
                    self.falhas[peer_id] = erros + 1
                    agora = time.time()
                    pendentes = self.ping_tempo.setdefault(peer_id, {})
                    pendentes[ping_msg["msg_id"]] = agora
                    pendentes["_ultimo"] = agora
                    if len(pendentes) > 10:
                        mais_antigo = next(k for k in pendentes if k != "_ultimo")
                        pendentes.pop(mais_antigo, None)
                    tentativa_atual = self.falhas[peer_id]

            if desconectar_peer:
                log.warning(f"[KeepAlive] {peer_id} Perdeu {self.miss_limit} pings seguidos -> Desconectando")
                self.ger_conex.desconectar(peer_id, motivo=f"Timeout de {self.miss_limit} pings")
                continue

            self.ger_conex.enviar(peer_id, ping_msg)
            log.debug(f"[KeepAlive] Ping para {peer_id} enviado (esperando pong {tentativa_atual})")
        return

    def tratar_msg(self, peer_id, msg):
        tipo = msg.get("type")

        if tipo == "PING": #ve se é ping se for manda pong
            ts = msg.get("timestamp")
            mid = msg.get("msg_id")
            self.ger_conex.enviar(peer_id, criar_pong(ts, msg_id=mid))
            log.debug(f"[KeepAlive] Pong respondido para {peer_id}")
            return True
        elif tipo == "PONG": #ve se é pong calcula o rtt
            mid = msg.get("msg_id")
            t_envio = None
            with self.lock:
                self.falhas[peer_id] = 0
                pendentes = self.ping_tempo.get(peer_id)
                if pendentes:
                    t_envio = pendentes.pop(mid, None)
                    if t_envio is not None:
                        if pendentes.get("_ultimo") == t_envio:
                            pendentes.pop("_ultimo", None)
                    else:
                        t_envio = pendentes.pop("_ultimo", None)
            try:
                if t_envio is not None:
                    rtt_ms = (time.time() - t_envio) * 1000 #pega o tempo e dps faz vira ms
                    self.peer_table.calc_rtt(peer_id, rtt_ms)
            except Exception as e:
                log.warning(f"[KeepAlive] Erro no RTT de {peer_id}: {e}")

            return True
        return False