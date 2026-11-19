######################################
#Eduardo Kachel Pereira: 241009780   #
#João Pedro Martins França: 241009815#
#Thiago Rocha Gomes Urbano: 241040646#
######################################
import socket
import threading
import logging
import json
import uuid

import json_handler as jh

log = logging.getLogger("peer_connection")

def env_msg(sock, dado):
    linha = json.dumps(dado) + "\n"
    sock.sendall(linha.encode("utf-8"))
    log.debug(f"-> {linha.strip()}")
    return

def hello(meu_peer_id, features=None):
    if features is None:
        features = ["hangman"]
    return { #mensagem de hello para estabelecer a conexao
        "type": "HELLO",
        "msg_id": str(uuid.uuid4()),
        "ttl": 1,
        "peer_id": meu_peer_id,
        "version": "1.0",
        "features": features
    }

def hello_ok(meu_peer_id, features=None, msg_id=None):
    if features is None:
        features = ["hangman"]
    return { #hello_ok confirma o recebimento
            "type": "HELLO_OK",
            "msg_id": msg_id if msg_id else str(uuid.uuid4()),
            "ttl": 1,
            "peer_id": meu_peer_id,
            "version": "1.0",
            "features": features
        }

def bye(meu_peer_id, dest, motivo="closing"):
    return { #msg para fechar conexao
        "type": "BYE",
        "msg_id": str(uuid.uuid4()),
        "ttl": 1,
        "src": meu_peer_id,
        "dst": dest,
        "reason": motivo
    }
def bye_ok(meu_peer_id, dest, msg_id=None):
    return { #confirmação do fechamento
        "type": "BYE_OK",
        "msg_id": msg_id if msg_id else str(uuid.uuid4()),
        "ttl": 1,
        "src": meu_peer_id,
        "dst": dest
    }

class ger_conex: #gerenciamento da conexao dos peers
    def __init__(self, meu_peer_id, peer_table, porta, on_mensagem=None, on_desconexao=None):
        self.meu_peer_id = meu_peer_id
        self.peer_table = peer_table
        self.porta = int(porta)
        self.on_mensagem = on_mensagem
        self.on_desconexao = on_desconexao

        self.conexoes ={}
        self.send_locks = {}
        self.lock = threading.RLock()

        self.serv_sock = None
        self.rodando = True

    def _enviar_sock(self, sock, dado):
        with self.lock:
            send_lock = self.send_locks.get(sock)
        if send_lock:
            with send_lock:
                env_msg(sock, dado)
        else:
            env_msg(sock, dado)

    def init_serv(self): #inicializaçao do socket e serv
        self.serv_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.serv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.serv_sock.bind(("0.0.0.0", self.porta))
        self.serv_sock.listen(5)
        log.info(f"[Servidor] Ouvindo conexoes na porta {self.porta}")

        escuta = threading.Thread(target=self.loop_escuta, daemon=True)
        escuta.start()
        return

    def loop_escuta(self): #fica ouvindo e avisa qnd recerber conex
        while self.rodando:
            try:
                cliente_sock, endereco = self.serv_sock.accept()
                log.debug(f"[Servidor] Nova conexao recebida de {endereco}")

                hs= threading.Thread(target=self.handshakein, args=(cliente_sock, endereco), daemon=True)
                hs.start()
            except Exception as e:
                if self.rodando:
                    log.error(f"[Servidor] Erro no accept: {e}")
                break
        return

    def handshakein(self, cliente_sock, endereco): #processo de handshake
        arquivo = None
        try:
            cliente_sock.settimeout(5.0)
            arquivo = cliente_sock.makefile("rb")

            msg = jh.ler_linha_socket(arquivo)
            if not msg:
                cliente_sock.close()
                return
            log.debug(f"<- {json.dumps(msg)}")

            if msg.get("type") != "HELLO":
                log.warning(f"[Handshake IN] Esperava HELLO de {endereco}, mas veio {msg.get('type')}")
                cliente_sock.close() #recebeu relou errado encerra tentativa de conex
                return

            peer_id = msg.get("peer_id")
            features = msg.get("features", [])

            with self.lock:
                if peer_id in self.conexoes:#ve se ja n ta conectado
                    log.info(f"[Handshake IN] Conexao duplicada com {peer_id}")
                    if self.meu_peer_id <peer_id:
                        env_msg(cliente_sock, bye(self.meu_peer_id, peer_id, motivo="duplicate"))
                        cliente_sock.close()
                        return
                    else:
                        antiga = self.conexoes.pop(peer_id,None)
                        if antiga:
                            try:
                                antiga.close()
                            except:
                                pass

            resp = hello_ok(self.meu_peer_id, msg_id=msg.get("msg_id"))
            env_msg(cliente_sock, resp)

            cliente_sock.settimeout(None)

            with self.lock:
                self.conexoes[peer_id] = cliente_sock
                self.send_locks[cliente_sock] = threading.Lock()

            self.peer_table.conectado(peer_id, direcao= "INBOUND", features=features)
            log.info(f"[Handshake IN] Conectado com sucesso com {peer_id}")

            self.loop_leitura(cliente_sock, arquivo, peer_id)

        except Exception as e:
            log.error(f"[Handshake IN] Falha no handshake com {endereco}: {e}")
            try:
                cliente_sock.close()
            except:
                pass

    def loop_leitura(self, sock, arquivo, peer_id): #fica ouvindo as msgs
        try:
            while self.rodando:
                try:
                    msg = jh.ler_linha_socket(arquivo)
                    if msg is None:
                        log.info(f"[Conexao] {peer_id} fechou a conexao")
                        break
                    log.debug(f"<- {json.dumps(msg)}")
                    jh.validar_destinatario(msg, self.meu_peer_id)
                    if msg.get("type") == "BYE":
                        log.info(f"[Conexao] {peer_id} enviou BYE (motivo: {msg.get('reason')})")
                        try:
                            self._enviar_sock(sock, bye_ok(self.meu_peer_id, peer_id, msg_id=msg.get("msg_id")))#se recebeu bye manda bye ok de volta
                        except:
                            pass
                        break
                    if self.on_mensagem:
                        self.on_mensagem(peer_id, msg)#trata a msg

                except jh.MensagemDescartada:
                    continue

                except jh.ErroMensagem as e:
                    log.warning(f"[Conexao] Mensagem invalida de {peer_id}: {e}")
                    if e.responder:
                        msg_erro = jh.criar_mensagem_erro(self.meu_peer_id, peer_id, e.code, e.message, e.ref_msg_id)
                        self._enviar_sock(sock, msg_erro)

        except Exception as e:
            log.warning(f"[Conexao] Erro na conexao com {peer_id}: {e}")

        finally:
            with self.lock:
                if self.conexoes.get(peer_id) == sock:
                    self.conexoes.pop(peer_id, None)
                    era_ativa = True
                else:
                    era_ativa = False
                self.send_locks.pop(sock, None)

            try:
                sock.close()
            except:
                pass

            if era_ativa:
                self.peer_table.desconectou(peer_id, motivo="Conexao encerrada")
                log.info(f"[Conexao] Desconectado com {peer_id}")
                if self.on_desconexao:
                    try:
                        self.on_desconexao(peer_id)
                    except Exception as e:
                        log.error(f"[Conexao] Erro no callback on_desconexao: {e}")
        return

    def conect(self, peer_id, ip, porta): #ve se recebeu hello ok e conecta
        self.peer_table.conectando(peer_id)
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect((ip, int(porta)))

            env_msg(sock, hello(self.meu_peer_id))

            arquivo = sock.makefile("rb")
            resp = jh.ler_linha_socket(arquivo)
            if not resp or resp.get("type") != "HELLO_OK":
                raise Exception(f"Esperava HELLO_OK, mas veio {resp.get('type') if resp else 'nada'}")
            log.debug(f"<- {json.dumps(resp)}")

            sock.settimeout(None)

            with self.lock:
                self.conexoes[peer_id] = sock
                self.send_locks[sock] = threading.Lock()

            self.peer_table.conectado(peer_id, direcao= "OUTBOUND", features=resp.get("features", []))
            log.info(f"[Handshake OUT] Conectado com {peer_id}")

            leitura = threading.Thread(target=self.loop_leitura, args=(sock, arquivo, peer_id), daemon=True)
            leitura.start()

        except Exception as e:
            info = self.peer_table.obter_peer(peer_id)
            tentativa = (info.get("tentativas", 0) + 1) if info else 1
            if tentativa <= 1:
                log.warning(f"[Conexao] Falha ao conectar em {peer_id} ({ip}:{porta}): {e}")
            else:
                log.debug(f"[Conexao] Retentativa falhou em {peer_id} ({ip}:{porta}): {e}")
            self.peer_table.falha(peer_id, str(e))
            try:
                if sock:
                    sock.close()
            except:
                pass

        return

    def enviar(self, peer_id, dado): #envia msg
        with self.lock:
            sock = self.conexoes.get(peer_id)
            send_lock = self.send_locks.get(sock) if sock else None

        if not sock:
            log.warning(f"[Conexao] Nao tem conexao ativa com {peer_id}")
            return False

        try:
            if send_lock:
                with send_lock:
                    env_msg(sock, dado)
            else:
                env_msg(sock, dado)
            return True
        except Exception as e:
            log.warning(f"[Conexao] Erro ao enviar mensagem para {peer_id}: {e}")
            return False

    def broadcast(self, dado): #envia msg para todos os peers
        with self.lock:
            todos = list(self.conexoes.keys())

        for peer_id in todos:
            self.enviar(peer_id, dado)

        return

    def desconectar(self, peer_id, motivo = "closing"): #desconecta dos peers
        with self.lock:
            sock = self.conexoes.pop(peer_id, None)
            send_lock = self.send_locks.get(sock) if sock else None

        if sock:
            try:
                if send_lock:
                    with send_lock:
                        env_msg(sock, bye(self.meu_peer_id, peer_id, motivo=motivo))
                else:
                    env_msg(sock, bye(self.meu_peer_id, peer_id, motivo=motivo))
            except:
                pass
            try:
                sock.close()
            except:
                pass
            self.peer_table.desconectou(peer_id, motivo=motivo)
            log.info(f"[Conexao] Desconectou de {peer_id}")
            if self.on_desconexao:
                try:
                    self.on_desconexao(peer_id)
                except Exception as e:
                    log.error(f"[Conexao] Erro no callback on_desconexao: {e}")

        return

    def parar(self):#para o socket/serv
        self.rodando = False
        with self.lock:
            peers = list(self.conexoes.keys())
        for peer_id in peers:
            self.desconectar(peer_id, motivo="shutdown")

        if self.serv_sock:
            try:
                self.serv_sock.close()
            except:
                pass
        log.info("[Servidor] Finalizado")

        return