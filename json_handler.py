import json
import uuid
import logging

TML = 32768  # Tamanho máximo de linha em bytes (32 KiB)
log = logging.getLogger("message_router")

# Tipos de mensagens conhecidos
TIPOS_VALIDOS = {
    "HELLO", "HELLO_OK",
    "PING", "PONG",
    "BYE", "BYE_OK",
    "ERROR",
    "GAME_LIST", "GAME_LIST_OK",
    "JOIN", "JOIN_OK", "JOIN_ERR",
    "LEAVE", "LEAVE_OK",
    "GAME_START", "STATE",
    "GUESS", "GUESS_RESULT",
    "GAME_OVER"
}

# Mensagens que não possuem src e dst
MENSAGENS_SEM_SRC_DST = {
    "HELLO", "HELLO_OK", "PING", "PONG"
}

# Códigos de erro do protocolo
CODIGOS_ERRO = {
    "unknown_type", "bad_request",
    "not_for_me", "invalid_state", "bad_json"
}


class ErroMensagem(Exception):

    def __init__(self, code, message, ref_msg_id=None,
                 responder=True, src_original=None):

        super().__init__(message)
        self.code = code
        self.message = message
        self.ref_msg_id = ref_msg_id
        self.responder = responder
        self.src_original = src_original


class MensagemDescartada(Exception):
    pass


# Gera um erro padronizado
def gerar_erro(dados, code, message):

    ref = dados.get("msg_id")
    if not isinstance(ref, str):
        ref = None

    responder = dados.get("type") != "ERROR"

    raise ErroMensagem(
        code,
        message,
        ref_msg_id=ref,
        responder=responder,
        src_original=dados.get("src")
    )


# Verifica se um campo existe e possui o tipo esperado
def verificar_tipo(dados, campo, tipo):

    if campo not in dados:
        gerar_erro(dados, "bad_request",
                   f"Campo obrigatório ausente: {campo}")

    valor = dados[campo]

    valido = type(valor) is int if tipo is int else isinstance(valor, tipo)

    if not valido:
        gerar_erro(dados, "bad_request",
                   f"Tipo inválido no campo: {campo}")


# Lê uma linha do socket TCP (até 32 KiB) e interpreta o JSON
def ler_linha_socket(arquivo_socket):

    linha = arquivo_socket.readline(TML + 1)

    if not linha:
        return None  # Conexão fechada (EOF)

    if len(linha) > TML:
        raise ErroMensagem(
            "bad_request",
            "Tamanho máximo de linha excedido (32 KiB)",
            responder=False
        )

    if not linha.strip():
        raise MensagemDescartada("Linha vazia")

    return ler_mensagem(linha)


# Lê e interpreta uma mensagem JSON
def ler_mensagem(mensagem):

    if len(mensagem) > TML:
        raise ErroMensagem(
            "bad_request",
            "Tamanho máximo de linha excedido (32 KiB)",
            responder=False
        )

    try:
        texto = mensagem.decode("utf-8")
        dados = json.loads(texto)

    except UnicodeDecodeError:
        raise ErroMensagem("bad_json", "Codificação UTF-8 inválida")

    except json.JSONDecodeError:
        raise ErroMensagem("bad_json", "JSON inválido")

    if not isinstance(dados, dict):
        raise ErroMensagem(
            "bad_request",
            "A mensagem deve ser um objeto JSON"
        )

    validar_mensagem(dados)
    return dados


# Valida o envelope da mensagem
def validar_mensagem(dados):

    verificar_tipo(dados, "type", str)
    tipo = dados["type"]

    verificar_tipo(dados, "msg_id", str)
    verificar_tipo(dados, "ttl", int)

    # TTL diferente de 1 deve ser descartado
    if dados["ttl"] != 1:
        raise MensagemDescartada("TTL diferente de 1")

    # Verifica src e dst
    if tipo not in MENSAGENS_SEM_SRC_DST:
        verificar_tipo(dados, "src", str)
        verificar_tipo(dados, "dst", str)

    # Verifica se o tipo é conhecido
    if tipo not in TIPOS_VALIDOS:
        gerar_erro(
            dados,
            "unknown_type",
            f"Tipo desconhecido: {tipo}"
        )

    # Timestamp obrigatório em PING/PONG
    if tipo in {"PING", "PONG"}:
        verificar_tipo(dados, "timestamp", str)

    # Timestamp opcional nas demais mensagens
    elif "timestamp" in dados:
        verificar_tipo(dados, "timestamp", str)

    # Valida campos específicos essenciais
    if tipo in {"HELLO", "HELLO_OK"}:

        verificar_tipo(dados, "peer_id", str)
        verificar_tipo(dados, "version", str)
        verificar_tipo(dados, "features", list)

        for feature in dados["features"]:
            if not isinstance(feature, str):
                gerar_erro(
                    dados,
                    "bad_request",
                    "features deve conter strings"
                )

    elif tipo == "BYE":
        verificar_tipo(dados, "reason", str)

    elif tipo == "ERROR":

        verificar_tipo(dados, "code", str)
        verificar_tipo(dados, "message", str)

        if dados["code"] not in CODIGOS_ERRO:
            gerar_erro(
                dados,
                "bad_request",
                "Código de erro desconhecido"
            )

        if "ref_msg_id" in dados:
            verificar_tipo(dados, "ref_msg_id", str)


# Verifica se a mensagem foi destinada ao peer local
def validar_destinatario(dados, peer_id_local):

    if dados["type"] in MENSAGENS_SEM_SRC_DST:
        return True

    if dados["dst"] != peer_id_local:
        gerar_erro(
            dados,
            "not_for_me",
            "Mensagem destinada a outro peer"
        )

    return True


# Cria uma mensagem ERROR no formato do protocolo
def criar_mensagem_erro(src, dst, code, message, ref_msg_id=None):

    if code not in CODIGOS_ERRO:
        raise ValueError("Código de erro inválido")

    erro = {
        "type": "ERROR",
        "msg_id": str(uuid.uuid4()),
        "src": src,
        "dst": dst,
        "ttl": 1,
        "code": code,
        "message": message
    }

    if ref_msg_id is not None:
        erro["ref_msg_id"] = ref_msg_id

    return erro
