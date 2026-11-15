import time
import uuid
import logging
import threading

log = logging.getLogger("keep_alive")

def criar_ping():
    return {
        "type": "PING",
        "msg_id": str(uuid.uuid4()),
        "ttl": 1,
        "timestamp": str(time.time()),
    }

def criar_pong(timestamp_original):
    return {
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
            time.sleep(self.intervalo)
            if self.rodando:
                self.enviar_ping()
        return

    def enviar_ping(self):
        conect = self.peer_table.list_conect()

        for peer_id in conect:
            with self.lock:
                erros = self.falhas.get(peer_id, 0)

                if erros >= 3:
                    log.warning(f"[KeepAlive] {peer_id} Perdeu 3 pings seguidos -> Desconctando")
                    self.falhas.pop(peer_id, None)
                    self.ger_conex.desconectar(peer_id, motivo="Timeout de 3 pings")
                    continue
                self.falhas[peer_id] = erros+1

            self.ger_conex.enviar(peer_id, criar_ping())
            log.debug(f"[KeepAlive] Ping para {peer_id} enviado (esperando pong {self.falhas[peer_id]})")
        return

    def tratar_msg(self, peer_id, msg):
        tipo = msg.get("type")

        if tipo == "PING":
            ts = msg.get("timestamp")
            self.ger_conex.enviar(peer_id, criar_pong(ts))
            log.debug(f"[KeepAlive] Pong respondido para {peer_id}")
            return True
        elif tipo == "PONG":
            with self.lock:
                self.falhas[peer_id] = 0
            try:
                ts = float(msg.get("timestamp"))
                rtt_ms = (time.time()-ts)*1000
                (self.peer_table.calc_rtt(peer_id, rtt_ms))
            except Exception as e:
                log.warning(f"[KeepAlive] Erro no RTT de {peer_id}: {e}")

            return True
        return False