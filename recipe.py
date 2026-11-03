"""
recipe.py — Constantes ESPECÍFICAS do carro/módulo para o Ford Focus Mk2 (C307).

Este arquivo é o "mapa" que diz ao programa COMO ler e gravar a opção de
temperatura no painel (IPC). Ele está separado do código de transporte de
propósito: o transporte (ELM327 + ISO-TP) é padrão e confiável; o que muda de
carro para carro — e o que é PERIGOSO errar — mora tudo aqui.

┌──────────────────────────────────────────────────────────────────────────┐
│  ATENÇÃO                                                                   │
│                                                                            │
│  Enquanto VERIFICADO = False, o programa roda em modo SOMENTE-LEITURA.     │
│  Ele NÃO vai gravar nada no carro. Isso é intencional: gravar um byte      │
│  errado (offset, bit ou checksum incorretos, ou sem o Security Access      │
│  correto) pode CORROMPER a configuração do painel.                         │
│                                                                            │
│  Os valores abaixo marcados como CANDIDATO são PALPITES iniciais baseados  │
│  no conhecimento geral da plataforma — NÃO são confirmados para o seu      │
│  carro. Eles precisam ser preenchidos a partir de uma fonte verificada:    │
│    (a) uma captura serial do ELM-FF2 fazendo essa mudança no seu carro, ou │
│    (b) engenharia reversa confirmada do ELM-FF2.                           │
└──────────────────────────────────────────────────────────────────────────┘
"""

from dataclasses import dataclass, field


# Vira True SOMENTE quando cada campo abaixo tiver sido confirmado por captura
# ou RE. Enquanto False, qualquer tentativa de gravação é recusada pelo programa.
VERIFICADO = False


@dataclass
class Recipe:
    # ---- Adaptador / porta serial ----
    porta: str = "COM3"          # ex.: "COM3" no Windows, "/dev/ttyUSB0" no Linux
    baud: int = 38400            # 38400 ou 115200 (clones variam)

    # ---- Barramento CAN do módulo IPC ----
    # No Focus Mk2 o IPC normalmente responde na MS-CAN (125 kbit/s), NÃO na
    # HS-CAN (500 kbit/s) do motor. Por isso um adaptador com chave HS/MS-CAN
    # (ou multiplexado, tipo OBDLink EX) costuma ser obrigatório.
    usar_ms_can: bool = True     # CANDIDATO: IPC do Mk2 tende a ficar na MS-CAN

    # Comandos ELM327 para selecionar o protocolo.
    #  - HS-CAN 11bit/500k  -> ["ATSP6"]
    #  - MS-CAN 11bit/125k  -> protocolo custom; varia MUITO por adaptador.
    # CANDIDATO (ajustar conforme o adaptador):
    protocolo_hs: tuple = ("ATSP6",)
    protocolo_ms: tuple = ("ATSP6",)  # placeholder; muitos adaptadores usam a
                                       # chave física + 125k interno. Ver README.

    # IDs CAN de diagnóstico do IPC (11-bit). CANDIDATO — CONFIRMAR.
    id_requisicao: int = 0x720   # header que o ELM327 usa p/ falar com o IPC
    id_resposta: int = 0x728     # id que o IPC usa p/ responder (req + 8, típico)

    # ---- Como LER o bloco de configuração do IPC ----
    # Sequência de serviços de diagnóstico até conseguir ler a config.
    # CANDIDATO — placeholders. Serão preenchidos pela captura/RE.
    # Cada item é uma lista de bytes (a carga do serviço, SEM o PCI do ISO-TP).
    sessao_diagnostica: tuple = (0x10, 0x85)   # StartDiagnosticSession (KWP, CANDIDATO)
    requisicao_leitura: tuple = ()              # ex.: (0x21, 0x..) ou (0x22, 0xHH,0xLL) — DESCONHECIDO
    offset_resposta_dados: int = 0              # onde, na resposta, começam os dados úteis

    # ---- Localização do bit da temperatura dentro do bloco ----
    # No ELM-FF2 a opção aparece como CheckBoxIPC34 ("Simulated engine temp") e
    # CheckBoxIPC36 ("Real engine temp"). O índice (34/36) precisa ser traduzido
    # para byte+bit reais do bloco de config. DESCONHECIDO até verificação.
    byte_offset_temp: int = -1   # -1 = desconhecido
    bit_temp: int = -1           # -1 = desconhecido
    # Interpretação do bit: True nesse bit significa "temperatura REAL"?
    bit_set_significa_real: bool = True

    # ---- Como GRAVAR de volta ----
    requer_security_access: bool = True   # CANDIDATO: assumir que SIM por segurança
    security_request_seed: tuple = (0x27, 0x01)
    security_send_key: tuple = (0x27, 0x02)
    # Algoritmo seed->key: DESCONHECIDO. Preenchido só após RE/captura.
    seed_key_algoritmo = None
    requisicao_escrita: tuple = ()        # ex.: (0x3B, 0x..) + dados — DESCONHECIDO

    # Checksum do bloco (muitos módulos Ford exigem recalcular). DESCONHECIDO.
    tipo_checksum: str = "desconhecido"   # "nenhum" | "soma8" | "crc16" | ...


def recipe_padrao() -> Recipe:
    return Recipe()
