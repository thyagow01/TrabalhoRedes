import json
import socket
import logging

TML = 32768 #tamanho maximo de linha em bytes
log = logging.getLogger("rendezvous_connection")

class RendezvousConnection:
    def __init__(self, host: str, port: int, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout

    def request(self, payload):
        mensagem = json.dumps(payload) + "\n" #converte para json
        dados = mensagem.encode("utf-8") #converte para bytes

        if len(dados) > TML: #se numero de bytes for maior da erro
            raise ValueError("Tamanho de mensagens excedido")

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s: #abre socket
            s.settimeout(self.timeout)#define o timeout
            s.connect((self.host, self.port))#conecta
            log.debug("[RDV] → %s", mensagem.strip())
            s.sendall(dados) #envia os dados usa all pra mandar tudo send pode acabar cortando

            with s.makefile('rb') as f: #le resposta
                linha = f.readline(TML+1)

        if len(linha) > TML:
            raise ValueError("Tamanho de mensagens excedido")

        texto =linha.decode("utf-8", errors="replace").strip() #limpa o texto de \r e\n e decodifica
        log.debug("[RDV] ← %s", texto)

        if not texto:
            raise RuntimeError("Sem resposta")

        resposta = json.loads(texto)
        if resposta.get("status") != "OK":
            raise RuntimeError(resposta.get("message","Erro no Rendezvous"))

        return resposta

    def register(self, namespace, name, port, ttl=7200):
        payload ={
            "type": "REGISTER",
            "namespace": namespace,
            "name": name,
            "port": int(port),
            "ttl": int(ttl),
        }
        resposta = self.request(payload)
        log.info(
            "[RDV] registered %s@%s as %s:%s (ttl=%s)",
            name, namespace, resposta.get("ip"), resposta.get("port"), resposta.get("ttl")
        )
        return resposta

    def discover(self, namespace = None):
        payload ={
            "type": "DISCOVER",
        }
        if namespace: #se tiver namespace passa junto para puxer so de la
            payload["namespace"] = namespace

        resposta = self.request(payload) #joga na função para criar o socket e pedir dado
        peers = resposta.get("peers", [])
        return peers

    def unregister(self, namespace, name=None, port=None): #pede pra sair
        payload = {
            "type": "UNREGISTER",
            "namespace": namespace,
        }
        if name is not None: #se tiver mais de um no mesmo ip tira todos, pode especificar com nome e porta
            payload["name"] = name
        if port is not None:
            payload["port"] = int(port)

        resposta = self.request(payload)
        log.info("[RDV] unregistered %s@%s (port=%s)", name, namespace, port)
        return resposta

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    rdv = RendezvousConnection("pyp2p.mfcaetano.cc", 8080)
    registro = rdv.register("teste","joao", 8081, ttl=60)
    #print("Registrado:", registro)
    peers = rdv.discover("teste")
    #print("Peers:", peers)
    desregistrar = rdv.unregister("teste", "joao", 8081)
    #print("Desregistrado:", desregistrar)




