# -*- coding: utf-8 -*-
"""
capture.py — Transforma uma CAPTURA do ELM-FF2 (log serial) na "receita"
(recipe.py), de forma automática e auditável.

Por que isto existe: a análise estática do ELM-FF2 (Ghidra) NÃO revela com
segurança os bytes do protocolo (IDs CAN, Security Access, serviço de
leitura/escrita, offset/bit, checksum) — eles são montados em runtime. A fonte
confiável é observar o próprio ELM-FF2 fazendo a troca no seu carro. Este módulo
lê esse log e reconstrói as mensagens de diagnóstico.

Formato de entrada aceito (tolerante):
  • Linhas com direção explícita no começo são o ideal:
        >> ATSH720          (enviado p/ o adaptador)
        << OK
        >> 1085
        << 720 06 50 85 ...  (resposta do módulo)
    Prefixos aceitos p/ ENVIO: ">>", "TX", "TX:", "SEND", "->"
    Prefixos aceitos p/ RECEBIDO: "<<", "RX", "RX:", "RECV", "<-"
  • Sem prefixo, o parser usa heurística: linhas "AT..." e a linha de hex logo
    após um ">" são tratadas como ENVIO; o resto como RECEBIDO.
"""

import re

# Serviços de diagnóstico (KWP2000/UDS) para rotular as mensagens
SERVICOS = {
    0x10: "StartDiagnosticSession", 0x11: "ECUReset",
    0x14: "ClearDiagnosticInfo", 0x18: "ReadDTCByStatus",
    0x1A: "ReadECUIdentification", 0x21: "ReadDataByLocalId",
    0x22: "ReadDataByIdentifier", 0x23: "ReadMemoryByAddress",
    0x27: "SecurityAccess", 0x2E: "WriteDataByIdentifier",
    0x2C: "DynamicallyDefineDataId", 0x31: "RoutineControl/StartRoutine",
    0x34: "RequestDownload", 0x3B: "WriteDataByLocalId",
    0x3D: "WriteMemoryByAddress", 0x3E: "TesterPresent",
    0x85: "StartDiagnosticSession(KWP)",
}

_hexline = re.compile(r"^[0-9A-Fa-f ]+$")


def _classificar(linha):
    s = linha.strip()
    if not s:
        return None, None
    up = s.upper()
    for p in (">>", "TX:", "TX ", "SEND", "->"):
        if up.startswith(p):
            return "tx", s[len(p):].strip()
    for p in ("<<", "RX:", "RX ", "RECV", "<-"):
        if up.startswith(p):
            return "rx", s[len(p):].strip()
    # heurística sem prefixo
    if up.startswith("AT"):
        return "tx", s
    return "rx", s


def _frames(texto):
    """Extrai frames CAN (id, bytes) de um bloco de texto do ELM327 (ATH1)."""
    out = []
    for ln in texto.split("\n"):
        s = ln.strip()
        if not _hexline.match(s):
            continue
        h = s.replace(" ", "")
        if len(h) < 4 or len(h) % 2:
            # pode ser header de 3 dígitos + dados
            if len(h) >= 5 and len(h) % 2 == 1:
                cid = int(h[:3], 16); data = bytes.fromhex(h[3:])
                out.append((cid, data)); continue
            continue
        if len(h) >= 5:
            cid = int(h[:3], 16); data = bytes.fromhex(h[3:]) if len(h[3:]) % 2 == 0 else b""
            out.append((cid, data))
    return out


def _isotp(frames):
    """Remonta um PDU ISO-TP a partir de frames (assume 1 mensagem)."""
    dados = bytearray(); total = None
    for _cid, d in frames:
        if not d:
            continue
        pci = d[0] >> 4
        if pci == 0:
            n = d[0] & 0x0F; return bytes(d[1:1 + n])
        elif pci == 1:
            total = ((d[0] & 0x0F) << 8) | d[1]; dados += d[2:]
        elif pci == 2:
            dados += d[1:]
    return bytes(dados[:total]) if total else bytes(dados)


def analisar(texto_log):
    """Lê o log e devolve uma lista de eventos de diagnóstico."""
    header_atual = None
    eventos = []
    pend_tx = None  # (header, payload_bytes)

    for linha in texto_log.split("\n"):
        tipo, conteudo = _classificar(linha)
        if not tipo:
            continue
        up = conteudo.upper().replace(" ", "")
        if tipo == "tx":
            m = re.match(r"ATSH([0-9A-F]{3,8})", up)
            if m:
                header_atual = int(m.group(1), 16)
                continue
            if up.startswith("AT"):
                continue
            if _hexline.match(conteudo):  # requisição de diagnóstico enviada
                # Convenção CAF1: o que é digitado é o PDU do serviço, SEM PCI
                # (o ELM327 adiciona o PCI). Então não rodamos ISO-TP aqui.
                h = conteudo.replace(" ", "")
                if h and len(h) % 2 == 0:
                    payload = bytes.fromhex(h)
                    eventos.append(("REQ", header_atual, payload))
        else:  # rx
            frames = _frames(conteudo)
            if frames:
                resp = _isotp(frames)
                if resp:
                    eventos.append(("RESP", frames[0][0], resp))
    return eventos


def header_fmt(cid):
    return ("%03X" % cid) if cid is not None else ""


def resumir(eventos):
    """Imprime a linha do tempo e tenta deduzir a receita (diff leitura/escrita)."""
    print("Linha do tempo de diagnóstico:\n")
    leituras, escritas = [], []
    for ev in eventos:
        tag, cid, pdu = ev
        if not pdu:
            continue
        sid = pdu[0]
        if tag == "RESP" and sid & 0x40:
            nome = SERVICOS.get(sid - 0x40, "resp")
            print("  RESP %s  svc=%s  dados=%s" % (hx(cid), nome, pdu.hex().upper()))
            if (sid - 0x40) in (0x21, 0x22, 0x23):
                leituras.append(pdu[1:])
        elif tag == "REQ":
            nome = SERVICOS.get(sid, "?0x%02X" % sid)
            print("  REQ  %s  svc=%s  dados=%s" % (hx(cid), nome, pdu.hex().upper()))
            if sid in (0x3B, 0x2E, 0x3D):
                escritas.append(pdu)
        elif tag == "RESP" and sid == 0x7F:
            print("  RESP %s  NEGATIVO svc=0x%02X nrc=0x%02X" %
                  (hx(cid), pdu[1] if len(pdu) > 1 else 0, pdu[2] if len(pdu) > 2 else 0))

    print("\nSecurity Access (0x27) presente?",
          "SIM" if any(e[2] and e[2][0] in (0x27, 0x67) for e in eventos) else "não detectado")

    # diff: compara o último bloco lido com o bloco escrito para achar byte/bit
    if leituras and escritas:
        antes = leituras[-1]
        # a escrita costuma ser [svc][id...] + bloco; tenta alinhar pelo tamanho
        wr = escritas[-1]
        depois = wr[-len(antes):] if len(wr) >= len(antes) else wr[1:]
        print("\nTentando deduzir byte/bit alterado (leitura x escrita):")
        for i in range(min(len(antes), len(depois))):
            if antes[i] != depois[i]:
                dif = antes[i] ^ depois[i]
                bit = dif.bit_length() - 1
                print("  byte_offset=%d  bit=%d  (0x%02X -> 0x%02X)" %
                      (i, bit, antes[i], depois[i]))
    else:
        print("\n(Para deduzir byte/bit, a captura precisa conter a LEITURA do bloco "
              "e a ESCRITA logo em seguida.)")


def hx(cid):
    return "0x%03X" % cid if cid is not None else "0x???"
