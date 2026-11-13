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

                    if reg["status"] == Gone or (reg["status"] == Stale and (mudou_end or reregistro)):
                        reg["status"] = Discovered
                        reg["tentativas"] =0
                        reg["prox_tentativa"] =0.0
                        reg["last_error"] = None
                        log.debug(f"[PeerTable] Peer reaperono RDV: {peer_id} Discovered")

            for peer_id, reg in self.peers.items():
                if peer_id not in peers_agora and reg["status"] != Gone:
                    if reg["status"] == Connected:
                        desconectar_imd.append(peer_id)
                    reg["status"] = Gone
                    reg["direcao"] = None
                    log.info(f"[PeerTable] {peer_id} ausente no Rendezvous -> marcado como Gone")

        return desconectar_imd

