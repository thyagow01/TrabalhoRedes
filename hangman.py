########################################
# Grupo 11                             #
# Eduardo Kachel Pereira: 241009780    #
# João Pedro Martins França: 241009815 #
# Thiago Rocha Gomes Urbano: 241040646 #
########################################
import random
import unicodedata
import os
import hashlib

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARQUIVO_PALAVRAS_PADRAO = "words.txt"

MENSAGENS_ERRO = {
    "invalid_letter": "Letra inválida. Digite apenas uma letra de A a Z.",
    "letter_already_used": "Você já tentou essa letra.",
    "invalid_word": "Palavra inválida. Use de 3 a 20 letras de A a Z.",
}


#seçao para pegar as palavras do words.txt e incoporar ao jogo / A biblioteca os ajuda a rodar no linux
def _resolver_caminho(caminho):
    if os.path.isabs(caminho) or os.path.exists(caminho):
        return caminho
    return os.path.join(BASE_DIR, caminho)

def normalizar(palavra): #normaliza a palavra p minusculo e sem acento
    if not isinstance(palavra, str):
        raise ValueError("A palavra deve ser uma string.")
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", palavra.strip())     #   quebra "á" em "a" + "´"
        if unicodedata.category(c) != "Mn"           # joga os "´" fora
    )
    return sem_acento.lower()

def validar_palavra(palavra): # valida a palavra de acordo com as especificações do projeto(3-20 letras, A a Z)
    normalizada = normalizar(palavra)
    if not (3 <= len(normalizada) <= 20):
        raise ValueError("A palavra deve ter entre 3 e 20 caracteres.")
    if not all("a" <= c <= "z" for c in normalizada):
        raise ValueError("A palavra deve conter apenas letras de 'a' a 'z' (sem espaços ou símbolos).")
    return normalizada

def carregar_palavras(caminho=ARQUIVO_PALAVRAS_PADRAO):
    #funcao que le o arquivo das palavras e retorna erro se nao tiver palavras
    caminho = _resolver_caminho(caminho)
    with open(caminho, encoding="utf-8") as f:
        palavras = []
        for linha in f:
            bruta = linha.strip()
            if not bruta:     
                continue
            try:
                palavras.append(validar_palavra(bruta))
            except ValueError:
                continue

    if not palavras:
        raise ValueError(f"O arquivo {caminho} está vazio.")
        
    return palavras

def sortear_palavra(caminho=ARQUIVO_PALAVRAS_PADRAO): #sorteia a palavra aleatoria com base na lista retornada pelo carregar_palavras()
    return random.choice(carregar_palavras(caminho))


class JogoDaForca:

    ESTAGIOS_FORCA = [
        r"""
           +---+
           |   |
               |
               |
               |
               |
        =========
        """,
        r"""
           +---+
           |   |
           O   |
               |
               |
               |
        =========
        """,
        r"""
           +---+
           |   |
           O   |
           |   |
               |
               |
        =========
        """,
        r"""
           +---+
           |   |
           O   |
          /|   |
               |
               |
        =========
        """,
        r"""
           +---+
           |   |
           O   |
          /|\  |
               |
               |
        =========
        """,
        r"""
           +---+
           |   |
           O   |
          /|\  |
          /    |
               |
        =========
        """,
        r"""
           +---+
           |   |
           O   |
          /|\  |
          / \  |
               |
        =========
        """
    ]

    def __init__(self, palavra_secreta, vidas=6):
        if not isinstance(vidas,int) or vidas <= 0:
            raise ValueError("O número de vidas deve ser um inteiro positivo")
        
        self.palavra_secreta = validar_palavra(palavra_secreta)

        self.vidas_iniciais = vidas
        self.vidas_restantes = vidas

        self.letras_tentadas = set()
        self.letras_erradas = []
        self._mascara = ["_"] * len(self.palavra_secreta)

    @property
    def tentativas_erradas(self):
        return len(self.letras_erradas)

    def obter_word_hash(self):           #criptografa a palavra secreta
        return hashlib.sha256(self.palavra_secreta.encode("utf-8")).hexdigest()

    def obter_mascara(self):
        return "".join(self._mascara)  #string pro json da "pala_ra" (palavra sem a letra chutada)

    def obter_estado_formatado(self):
        return " ".join(self._mascara)
    
    def tentar_letra(self, letra):   #chute da letra
        if not isinstance(letra, str) or len(letra.strip()) != 1:
            raise ValueError("invalid_letter")

        chave = normalizar(letra)

        if len(chave) != 1 or not ("a" <= chave <= "z"):
            raise ValueError("invalid_letter")

        if chave in self.letras_tentadas:
            raise ValueError("letter_already_used")

        self.letras_tentadas.add(chave)

        reveladas = 0
        for i, c in enumerate(self.palavra_secreta):
            if c == chave:
                self._mascara[i] = chave
                reveladas += 1

        if reveladas > 0:
            return True, reveladas    #retorna (acertou:True , qtd de letras reveladas)

        self.letras_erradas.append(chave)                #errou a letra
        self.vidas_restantes = max(0, self.vidas_restantes - 1)
        return False, 0

    def tentar_palavra(self, palavra):    #chute da palavra
        try:
            palpite = validar_palavra(palavra)
        except ValueError:
            raise ValueError("invalid_word")

        if palpite == self.palavra_secreta:
            ocultas = self._mascara.count("_")
            self._mascara = list(self.palavra_secreta)
            return True, ocultas         #retorna (acertou, pontos ganhos(_ restantes))

        self.vidas_restantes = max(0, self.vidas_restantes - 1)
        return False, 0

    def verificar_vitoria(self):
        return "_" not in self._mascara  #vitoria se nao houver mais '_'

    def verificar_derrota(self):
        return self.vidas_restantes <= 0

    def finalizado(self):
        return self.verificar_vitoria() or self.verificar_derrota()

    def desenho_forca(self):        #ajuste para variação da vidas(devido ao .config de outros jogos)
        erros = self.vidas_iniciais - self.vidas_restantes
        max_idx = len(self.ESTAGIOS_FORCA) - 1
        indice = min(max_idx, round((erros / self.vidas_iniciais) * max_idx))
        return self.ESTAGIOS_FORCA[indice]

def jogar():  # teste no terminal
    palavra_escolhida = sortear_palavra()

    jogo = JogoDaForca(palavra_escolhida)

    print("==================================")
    print("          JOGO DA FORCA           ")
    print("==================================")

    while not jogo.finalizado():
        print(jogo.desenho_forca())
        print(f"Palavra: {jogo.obter_estado_formatado()}")
        print(f"Erros: {','.join(jogo.letras_erradas) or '-'}")
        print(f"Vidas: {jogo.vidas_restantes}/{jogo.vidas_iniciais}")

        entrada = input("\nDigite uma letra (ou a palavra inteira): ").strip()
        if not entrada:
            continue

        try:
            if len(entrada) == 1:
                acertou, pontos = jogo.tentar_letra(entrada)
            else:
                acertou, pontos = jogo.tentar_palavra(entrada)

            if acertou:
                print(f"\n[+] Boa! +{pontos} letra(s) revelada(s).")
            else:
                print("\n[-] Errou! Perdeu 1 vida.")

        except ValueError as e:
            codigo = str(e)
            aviso = MENSAGENS_ERRO.get(codigo, codigo)
            print(f"\n[!] {aviso}")

    print(jogo.desenho_forca())
    if jogo.verificar_vitoria():
        print(f"Vitória! Você acertou a palavra: {jogo.palavra_secreta}")
    else:
        print(f"Perdeu! A palavra era: {jogo.palavra_secreta}")


if __name__ == "__main__":
    jogar()
