import logging
import threading
import time
from collections import deque

log = logging.getLogger("peer_table")

#definir 5 estados que pode ter
Discovered = "DISCOVERED" #visto no discover no rdv sem conexão
Connecting = "CONNECTING" #tentando fazer handshake(abrir o tcp)
Connected = "CONNECTED" #handshake feito ok
Stale = "STALE" #conexão caiu
Gone = "GONE" #sumiu ou estorou o limite

class PeerTable:
    def __init__(self, meu_peer_id, base_backoff=2, max_backoff=60, max_tries=5):
        self.meu_peer_id = meu_peer_id #id proprio (nome@namespace)
        self.base_backoff = base_backoff #tempo de espera em seg
        self.max_backoff = max_backoff #tempo maximo
        self.max_tries = max_tries #tentativas ate dar gone

        self.peers = {} #dicionario com os id dos peers
        self.lock = threading.RLock() #evitar runtime error

    def criar_registro(self, peer_id, name, namespace, ip, porta, expiracao=None):
        return{
            "peer_id": peer_id,
            "name": name,
            "namespace": namespace,
            "ip": ip,
            "porta": int(porta),
            "status": Discovered,
            "direcao": None, #inboud conectou na gente, outbound a gente neles
            "features": [],
            "tentativas": 0,
            "prox_tentativa": 0.0,
            "last_error": None,
            "expiracao": expiracao,
            "rtts": deque(maxlen=10), #guarda os ultimos 10 rtt pra media
            "avg_rtt":None, #media do rtt
            "motivo_gone": None,
        }

    def update_discover(self, lista_peers):
        peers_agora = set()
        desconectar_imd=[]

        with self.lock:
            for peer in lista_peers:
                name = peer.get("name")
                namespace = peer.get("namespace")
                ip = peer.get("ip")
                porta = peer.get("port")
                if not (name and namespace and ip and porta):
                    continue

                peer_id = f"{name}@{namespace}"
                if peer_id == self.meu_peer_id:
                    continue

                peers_agora.add(peer_id)
                expiracao = peer.get("expires_in")

                if peer_id not in self.peers:
                    self.peers[peer_id] = self.criar_registro(
                        peer_id, name, namespace, ip, porta, expiracao
                    )
                    log.debug(f"[PeerTable] Peer {peer_id} adicionado à tabela (ip: {ip}, porta: {porta})")

                else:
                    reg = self.peers[peer_id]
                    mudou_end = (reg["ip"] !=ip or reg["porta"] != int(porta))

                    reregistro =(
                        expiracao is not None
                        and reg["expiracao"] is not None
                        and expiracao > reg["expiracao"]
                    )

                    reg["ip"] = ip
                    reg["porta"] = int(porta)
                    reg["expiracao"] = expiracao

                    if reg["status"] == Gone:
                        if mudou_end or reg.get("motivo_gone") == "ausente_rdv":
                            reg["status"] = Discovered
                            reg["tentativas"] = 0
                            reg["prox_tentativa"] = 0.0
                            reg["last_error"] = None
                            reg["motivo_gone"] = None
                            log.debug(f"[PeerTable] Peer reapareceu no RDV: {peer_id} -> Discovered")
                    elif reg["status"] == Stale and mudou_end:
                        reg["status"] = Discovered
                        reg["tentativas"] = 0
                        reg["prox_tentativa"] = 0.0
                        reg["last_error"] = None
                        log.debug(f"[PeerTable] Peer mudou endereço no RDV: {peer_id} -> Discovered")

            for peer_id, reg in self.peers.items():
                if peer_id not in peers_agora and reg["status"] != Gone:
                    if reg["status"] == Connected:
                        desconectar_imd.append(peer_id)
                    reg["status"] = Gone
                    reg["motivo_gone"] = "ausente_rdv"
                    reg["direcao"] = None
                    log.info(f"[PeerTable] {peer_id} ausente no Rendezvous -> marcado como Gone")

        return desconectar_imd

    def get_peers(self):
        cand = []
        agora = time.monotonic()
        with self.lock:
            for peer_id, reg in self.peers.items():
                if reg["status"] in (Discovered, Stale):
                    if agora >= reg["prox_tentativa"]:
                        cand.append((peer_id, reg["ip"], reg["porta"]))
                        reg["status"] = Connecting
                        reg["prox_tentativa"] = agora + 15.0
        return cand

    def resetar_tentativas(self):
        with self.lock:
            for reg in self.peers.values():
                if reg["status"] in (Stale, Gone):
                    reg["status"] = Discovered
                    reg["tentativas"] = 0
                    reg["prox_tentativa"] = 0.0
                    reg["last_error"] = None
                    reg["motivo_gone"] = None
            log.info("[PeerTable] Tentativas de reconexão resetadas")

    def conectando(self, peer_id):
        with self.lock:
            if peer_id in self.peers:
                self.peers[peer_id]["status"] = Connecting
                log.debug(f"[PeerTable] {peer_id} -> CONNECTING")

        return

    def conectado(self, peer_id, direcao, features=None):
        with self.lock:
            if peer_id not in self.peers:
                name, namespace = peer_id.split("@",1)
                self.peers[peer_id] = self.criar_registro(peer_id,name,namespace, ip="0.0.0.0", porta=0)
            reg = self.peers[peer_id]
            reg["status"] = Connected
            reg["direcao"] = direcao
            reg["features"]=features if features else []
            reg["tentativas"] = 0
            reg["prox_tentativa"] = 0.0
            reg["last_error"] = None
            log.info(f"[PeerTable] {peer_id} conectado {direcao}")
        return

    def falha(self, peer_id, erro):
        with self.lock:
            if peer_id in self.peers:
                reg = self.peers[peer_id]
                reg["tentativas"] += 1
                reg["last_error"] = str(erro)
                if reg["tentativas"] >= self.max_tries:
                    reg["status"] = Gone
                    reg["motivo_gone"] = "max_tries"
                    log.warning(f"[PeerTable] {peer_id} excedeu limite de tentativas ({self.max_tries}) -> GONE (não tentará mais)")
                else:
                    reg["status"] = Stale
                    espera = min(self.max_backoff, self.base_backoff * (2 ** (reg["tentativas"] - 1)))
                    reg["prox_tentativa"] = time.monotonic() + espera
                    log.debug(f"[PeerTable] {peer_id} vai esperar {espera} segundos para tentar novamente -> STALE")
        return

    def desconectou(self, peer_id, motivo):
        with self.lock:
            if peer_id in self.peers:
                reg = self.peers[peer_id]
                if reg["status"] == Connected:
                    reg["status"] = Stale
                    reg["direcao"] = None
                    reg["last_error"] = str(motivo)
                    reg["prox_tentativa"] = time.monotonic()+self.base_backoff
                    log.info(f"[PeerTable] Conexão com {peer_id} perdida ({motivo}) -> STALE")
        return

    def calc_rtt(self, peer_id, rtt_ms):
        with self.lock:
            if peer_id in self.peers:
                reg = self.peers[peer_id]
                reg["rtts"].append(rtt_ms)
                reg["avg_rtt"] = sum(reg["rtts"]) / len(reg["rtts"])
                log.debug(f"[PeerTable] RTT {peer_id}: {rtt_ms:.1f}ms (média: {reg['avg_rtt']:.1f}ms)")

        return

    def obter_peer(self, peer_id):
        with self.lock:
            if peer_id in self.peers:
                return dict(self.peers[peer_id])
            return None

    def list_conect(self):
        conectados = []
        with self.lock:
            for peer_id, reg in self.peers.items():
                if reg["status"] == Connected:
                    conectados.append(peer_id)
        return conectados

    def resumo(self):
        with self.lock:
            contagem = {Discovered: 0, Connecting: 0, Connected: 0, Stale: 0, Gone: 0}
            for reg in self.peers.values():
                stat = reg["status"]
                if stat in contagem:
                    contagem[stat] += 1
            return contagem
