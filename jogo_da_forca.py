import random
import unicodedata


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

    @staticmethod
    def _normalizar(texto): #normaliza a palavra p minusculo e sem acento
        sem_acento = "".join(
            c for c in unicodedata.normalize("NFD", texto)
            if unicodedata.category(c) != "Mn"
        )
        return sem_acento.lower()

    def __init__(self, palavra_secreta):
        self.palavra_secreta = palavra_secreta.strip()

        self._chaves = [self._normalizar(c) for c in self.palavra_secreta]
        self.letras_adivinhadas = set()
        self.tentativas_erradas = 0
        self.limite_erros = 6  # partes do corpo

    def _revelada(self, indice):
        letra = self.palavra_secreta[indice]

        return not letra.isalpha() or self._chaves[indice] in self.letras_adivinhadas

    def tentar_letra(self, letra):
        if len(letra) != 1 or not letra.isalpha():
            raise ValueError("Por favor, envie apenas uma letra válida.")

        chave = self._normalizar(letra)

        if chave in self.letras_adivinhadas:
            return False  # já tentou a letra

        self.letras_adivinhadas.add(chave)

        if chave not in self._chaves:
            self.tentativas_erradas += 1

        return True  # letra nova

    def obter_estado_palavra(self):
        estado = []
        for i, letra in enumerate(self.palavra_secreta):
            if not letra.isalpha():
                estado.append(letra)          # espaço aparece direto
            elif self._revelada(i):
                estado.append(letra)          # mostra as letras ja reveladas
            else:
                estado.append("_")            # letras nao reveladas sao '_'
        return " ".join(estado)

    def verificar_vitoria(self):
        return all(self._revelada(i) for i in range(len(self.palavra_secreta)))

    def verificar_derrota(self):
        return self.tentativas_erradas >= self.limite_erros

    def obter_desenho_forca(self):
        return self.ESTAGIOS_FORCA[self.tentativas_erradas]

    def obter_letras_tentadas(self):
        return ", ".join(sorted(l.upper() for l in self.letras_adivinhadas))


def jogar():  # teste no terminal
    palavras_disponiveis = ["Teste", "Banana", "Redes", "Flamengo", "Elden Ring", "Bom dia", "Servidor", "Rendezvous"]
    palavra_escolhida = random.choice(palavras_disponiveis)

    jogo = JogoDaForca(palavra_escolhida)

    print("==================================")
    print("   BEM-VINDO AO JOGO DA FORCA!    ")
    print("==================================")

    while not jogo.verificar_vitoria() and not jogo.verificar_derrota():
        print(jogo.obter_desenho_forca())
        print(f"Palavra: {jogo.obter_estado_palavra()}")
        print(f"Letras tentadas: {jogo.obter_letras_tentadas()}")
        print(f"Erros: {jogo.tentativas_erradas} de {jogo.limite_erros}")

        try:
            tentativa = input("\nDigite uma letra: ").strip()
            if not tentativa:
                continue

            sucesso = jogo.tentar_letra(tentativa)

            if not sucesso:
                print("\n[!] Você já tentou essa letra! Tente outra.")
            else:
                print("\n" + "=" * 30)

        except ValueError as e:
            print(f"\n[!] Erro: {e}")

    print(jogo.obter_desenho_forca())
    if jogo.verificar_vitoria():
        print(f"Vitória! Você acertou a palavra: {jogo.palavra_secreta}")
    else:
        print(f"Perdeu! A palavra era: {jogo.palavra_secreta}")


if __name__ == "__main__":
    jogar()