import time
import threading
import logging
import uuid
import sys
import json
from traceback import print_tb

from rendezvous_connection import RendezvousConnection
from peer_table import PeerTable
from peer_connection import ger_conex
from keep_alive import KeepAlive
from game_host import GameHost
from game_player import GamePlayer
import json_handler as jh

log = logging.getLogger("main")

class p2pno:
    def __init__(self, nome, namespace, porta = 9000, rdv_serv = "pyp2p.mfcaetano.cc", rdv_porta=8080, config =None):
        self.nome = nome
        self.namespace = namespace
        self.porta = int(porta)
        self.meu_peer_id = f"{nome}@{namespace}"
        self.config = config or {}

        #pega as configs do json se der pau pega o padrão que coloquei
        rdv_host = self.config.get("rdv_host", rdv_serv)
        rdv_p = int(self.config.get("rdv_port", rdv_porta))
        self.ttl = int(self.config.get("register_ttl", 7200))
        self.discover_interval = int(self.config.get("discover_interval", 20))
        ping_intevalo = int(self.config.get("ping_intevalo", 30))
        turno_timeout = int(self.config.get("turno_timeout", 30))
        aqv_palavras = self.config.get("words_file", "words.txt")
        vidas = int(self.config.get("lives", 6))
        max_players = int(self.config.get("max_players", 4))

        self.rdv = RendezvousConnection(rdv_host, rdv_p) #faz a conexão no servido porta do rdv
        self.tabela = PeerTable(self.meu_peer_id, base_backoff=int(self.config.get("base_backoff", 2)), max_backoff=int(self.config.get("max_backoff", 60)), max_tries=int(self.config.get("max_reconnect_attempts", 5))) #cria a tabela de peers e conecta com eles com o tempo de envio exponencial e maximo de tentativas
        self.geren = ger_conex(self.meu_peer_id, self.tabela, self.porta, on_mensagem=self.on_mensagem, on_desconexao=self.on_desconexao) # cria o gerenciador de conexões para enviar msgs de hello hello ok e bye e bye ok
        self.keepalive = KeepAlive(self.geren, self.tabela, intervalo=ping_intevalo) #fica mandando ping pong para ver se ta vivo

        self.host = GameHost(meu_peer_id=self.meu_peer_id, ger_conex=self.geren, vidas_padrao= vidas, max_players_padrao= max_players, turn_timeout= turno_timeout, arquivo_palavras= aqv_palavras, esta_jogando=lambda:self.player.esta_em_partida())
        self.player = GamePlayer(meu_peer_id=self.meu_peer_id, ger_conex= self.geren, peer_table= self.tabela,tem_jogo_host_fn=lambda: self.host.tem_partida_ativa())

        self.rodando =True
        self.thread_rdv = None

    def on_mensagem(self, peer_id, msg):
        if self.keepalive.tratar_msg(peer_id , msg):
            return

        tipo = msg.get("type")

        if tipo in ("GAME_LIST", "JOIN", "LEAVE", "GUESS"):  #msg que o host pode receber do player
            self.host.tratar_mensagem(peer_id , msg)
            return

        elif tipo in ("GAME_LIST_OK", "JOIN_OK", "JOIN_ERR", "LEAVE_OK", "GAME_START", "STATE", "GUESS_RESULT", "GAME_OVER", "ERROR"): #msg que o player pode receber do host
            self.player.tratar_mensagem(peer_id , msg)
            return

        log.debug(f"[Node] Mensagem não tratada de {peer_id}: {msg}")

    def on_desconexao(self, peer_id):
        if hasattr(self, "player") and self.player:
            self.player.on_peer_desconectado(peer_id)
        if hasattr(self, "host") and self.host:
            self.host.on_peer_desconectado(peer_id)
        log.debug(f"[Node] Erro na desconexão: {peer_id}")
        return

    def init(self):
        self.rodando = True
        self.geren.init_serv()
        self.exec_ciclo_rdv()
        self.keepalive.iniciar()
        self.thread_rdv = threading.Thread(target=self.loop_rdv, daemon=True)
        self.thread_rdv.start()
        log.info(f"[Node] {self.meu_peer_id} iniciado na porta {self.porta}")
        return

    def exec_ciclo_rdv(self):
        try:
            resp = self.rdv.register(self.namespace, self.nome, self.porta, ttl=self.ttl)
            if resp:
                meu_ip = resp.get("ip") if resp else None
            else:
                meu_ip = None
            peers = self.rdv.discover(self.namespace)
            desc = self.tabela.update_discover(peers)
            for peer_id in desc:
                self.geren.desconectar(peer_id, motivo="Removido do RDV")

            cand = self.tabela.get_peers()
            for peer_id, ip, porta in cand:
                t =threading.Thread(target=self.geren.conect, args=(peer_id, ip, porta), daemon=True)
                t.start()

        except Exception as e:
            log.error(f"[Node] Erro no RDV: {e}")

        return

    def loop_rdv(self):
        while self.rodando:
            for i in range(self.discover_interval):
                if not self.rodando:
                    return
                time.sleep(1)
            self.exec_ciclo_rdv()
        return

    def parar(self):
        self.rodando = False
        log.info(f"[Node] encerrando nó")

        try:
            if hasattr(self, "player") and self.player.esta_em_partida():
                self.player.sair_jogo()
            elif hasattr(self, "host") and self.host.tem_partida_ativa():
                self.host.cancelar_partida(motivo="host_shutdown")
        except Exception as e:
            log.debug(f"[Node] Erro ao encerrar partida: {e}")

        self.keepalive.parar()
        self.geren.parar()

        try:
            self.rdv.unregister(self.namespace, self.nome, self.porta)
        except Exception as e:
            log.debug(f"[Node] Erro no desregistro: {e}")

        log.info("[Node] Nó encerrado")

if __name__ == "__main__":
    cfg={}
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except:
        pass

    log_file = cfg.get("log_file")
    lh = [logging.StreamHandler()]
    if log_file:
        try:
            lh.append(logging.FileHandler(log_file, encoding="utf-8"))
        except:
            pass

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", handlers=lh)

    if len(sys.argv) >= 4:
        nome = sys.argv[1]
        namespace = sys.argv[2]
        porta = int(sys.argv[3])
    else:
        nome_def = cfg.get("name")
        ns_def = cfg.get("namespace")
        porta_def = cfg.get("listen_port")

        nome = input(f"Nome[{nome_def}]: ").strip() or nome_def
        namespace = input(f"Namespace[{ns_def}]: ").strip() or ns_def
        porta = str(input(f"Porta[{porta_def}]: ").strip())
        porta = int(porta) if porta else porta_def

    no = p2pno(nome,namespace,porta,config=cfg)
    no.init()

    print("Nó na rede, /help para comandos")

    try:
        while no.rodando:
            linha = input(f"[{no.meu_peer_id}] ").strip()
            if not linha:
                continue

            partes = linha.split()
            cmd = partes[0].lower()

            if cmd == "/peers":
                peers = no.rdv.discover(no.namespace)
                print(f"[CLI] peers no rendezvous {len(peers)} : {[p['name'] for p in peers]}")

            elif cmd in ("/conn", "/status_rede"):
                conectados = no.tabela.list_conect()
                print(f"[CLI] conexoes ativas {len(conectados)} :")
                for p in conectados:
                    info = no.tabela.obter_peer(p)
                    if not info: continue
                    rtt = f"{info['avg_rtt']:.1f}ms" if info.get("avg_rtt") is not None else "medindo"
                    print(f"{p} ({info['ip']}:{info.get('porta')}) [{info.get('direcao')} Ping: {rtt}")
                print()

            elif cmd == "/rtt":
                for p in no.tabela.list_conect():
                    info = no.tabela.obter_peer(p)
                    print(f"{p}: RTT medio = {info.get('avg_rtt')}ms")

            elif cmd == "/reconnect":
                no.tabela.resetar_tentativas()
                no.exec_ciclo_rdv()
                print("[CLI] Reconect forçado")

            elif cmd == "/create":
                palavra = partes[1] if len(partes) > 1 else None
                max_p = int(partes[2]) if len(partes) > 2 else None
                try:
                    if palavra == "--random" or not palavra:
                        partida = no.host.criar_partida(aleatoria=True, max_players=max_p)
                    else:
                        partida = no.host.criar_partida(palavra=palavra, max_players=max_p)
                    print(f"[CLI] patida criada com id {partida}")
                    print(f"[CLI] aguardando jogadores entrarem no {no.meu_peer_id}")
                except Exception as e:
                    print(f"Erro ao criar partida: {e}")

            elif cmd == "/start":
                try:
                    no.host.iniciar_partida()
                    print("[CLI] Partida iniciada")
                except Exception as e:
                    print(f"Erro ao iniciar partida: {e}")

            elif cmd == "/cancel":
                try:
                    ok = no.host.cancelar_partida()
                    if ok:
                        print("[CLI] Partida cancelada")
                    else:
                        print("[CLI] Sem partidas ativas")
                except Exception as e:
                    print(f"Erro ao cancelar partida: {e}")

            elif cmd == "/games":
                try:
                    print("[CLI] Partidas disponiveis:")
                    no.player.listar_jogos()
                except Exception as e:
                    print(f"Erro ao listar jogos: {e}")

            elif cmd == "/join":
                if len(partes) >1:
                    try:
                        no.player.entrar_jogo(partes[1])
                        print(f"[CLI] entrando em {partes[1]}")
                    except Exception as e:
                        print(f"Erro ao iniciar partida: {e}")
                else:
                    print("[CLI] para entrar digite /join <host_id>")

            elif cmd == "/leave":
                try:
                    no.player.sair_jogo()
                    print(f"[CLI] saiu do jogo")
                except Exception as e:
                    print(f"Erro ao sair: {e}")

            elif cmd == "/guess":
                if len(partes) >1:
                    try:
                        no.player.enviar_palpite_letra(partes[1])
                    except Exception as e:
                        print(f"Erro ao enviar palpite(letra): {e}")
                else:
                    print("[CLI] para enviar digite /guess <letra>")

            elif cmd == "/word":
                if len(partes) >1:
                    try:
                        no.player.enviar_palpite_palavra(partes[1])
                    except Exception as e:
                        print(f"Erro ao enviar palpite(palavra): {e}")
                else:
                    print("[CLI] para enviar digite /word <palavra>")

            elif cmd == "/status":
                if no.host.tem_partida_ativa():
                    print(no.host.obter_status_texto())
                elif no.player.esta_em_partida():
                    print(no.player.obter_status_texto())
                else:
                    print("[CLI} voce não está em nenhuma partida")

            elif cmd == "/log":
                if len(partes) >1:
                    nivel = getattr(logging, partes[1].upper(), logging.INFO)
                    logging.getLogger().setLevel(nivel)
                    print(f"[CLI] log alterado para {partes[1].upper()}")
                else:
                    print("[CLI] Selecione o nivel de log /log <DEBUG|INFO|WARNING|ERROR>")

            elif cmd == "/help":
                    print("Comandos:")
                    print("/games -> lista partidas")
                    print("/create <palavra> [max_players] ->cria partida")
                    print("/create --random [max_players] -> cria partida com palavra da lista")
                    print("/join <host_id> -> entra no jogo do host")
                    print("/start -> inicia partida(host)")
                    print("/cancel -> cancela partida(host)")
                    print("/guess <letra> -> chuta letra")
                    print("/word <palavra> -> chuta palavra")
                    print("/status -> ver status")
                    print("/conn -> ver conexões e latencia")
                    print("/peers -> lista os peers")
                    print("/leave -> sai da partida")
                    print("/quit -> sai do jogo e da rede")
            elif cmd in("/quit", "exit", "sair"):
                break
            else:
                print("[CLI] Comando não existe, digite /help e olha ai")
    except KeyboardInterrupt:
        print("\n matou no teclado")
    finally:
        no.parar()
        print("cabou")

