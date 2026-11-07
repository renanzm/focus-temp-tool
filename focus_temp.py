#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
focus_temp.py — Ferramenta mínima e open-source para trocar a indicação de
temperatura do motor no painel (IPC) do Ford Focus Mk2 de SIMULADA para REAL,
via adaptador ELM327 na OBD-II.

Filosofia: fazer UMA coisa só, com segurança. Nada de 50 opções inúteis.

═══════════════════════════════════════════════════════════════════════════
  SEGURANÇA — LEIA
═══════════════════════════════════════════════════════════════════════════
  • Gravar configuração num módulo do carro é irreversível se der errado e
    pode corromper o painel. Use por sua conta e risco.
  • Este programa SÓ grava quando a "receita" (recipe.py) estiver marcada como
    VERIFICADO = True. Enquanto isso, ele roda em modo somente-leitura.
  • Ele SEMPRE lê e salva um backup do bloco de configuração antes de gravar,
    e relê para conferir depois.
  • Tensão de bateria estável é obrigatória para gravar (use carregador).
═══════════════════════════════════════════════════════════════════════════

Dependência: pyserial  ->  pip install pyserial
"""

import argparse
import sys
import time
import datetime

try:
    import serial  # pyserial
except ImportError:
    serial = None

import recipe as recipe_mod


# ─────────────────────────────────────────────────────────────────────────
#  Camada de transporte: ELM327 + ISO-TP (ISO 15765-2)
#  Esta parte é PADRÃO e independe do carro — pode confiar nela.
# ─────────────────────────────────────────────────────────────────────────
class Elm327:
    def __init__(self, porta, baud=38400, debug=False, timeout=5):
        if serial is None:
            raise RuntimeError("pyserial não instalado. Rode: pip install pyserial")
        self.debug = debug
        self.ser = serial.Serial(porta, baud, timeout=timeout)
        time.sleep(0.2)

    def _log(self, direction, data):
        if self.debug:
            print("  [%s] %s" % (direction, data))

    def raw(self, cmd, espera=1.0):
        """Envia um comando ELM327 e devolve o texto da resposta até o prompt '>'."""
        self.ser.reset_input_buffer()
        self._log("TX", cmd)
        self.ser.write((cmd + "\r").encode("ascii"))
        buf = bytearray()
        t0 = time.time()
        while time.time() - t0 < espera + 2:
            b = self.ser.read(1)
            if not b:
                if buf:
                    break
                continue
            buf += b
            if b == b">":
                break
        txt = buf.decode("ascii", "replace").replace("\r", "\n")
        self._log("RX", txt.strip())
        return txt

    def init(self, protocolo_cmds):
        """Reset e configuração básica do ELM327 para ISO-TP manual."""
        for c in ["ATZ", "ATE0", "ATL0", "ATS0", "ATH1", "ATCAF0", "ATAL"]:
            self.raw(c, 1.0)
            time.sleep(0.05)
        for c in protocolo_cmds:
            self.raw(c, 1.0)

    def set_header(self, can_id):
        self.raw("ATSH%03X" % can_id)

    # ---- ISO-TP ----
    def _frames_rx(self, txt):
        """Extrai frames CAN (id, bytes) das linhas de texto do ELM327 (ATH1, ATS0)."""
        frames = []
        for linha in txt.split("\n"):
            s = linha.strip().replace(" ", "")
            if len(s) < 4 or not all(ch in "0123456789ABCDEFabcdef" for ch in s):
                continue
            can_id = int(s[:3], 16)
            data = bytes.fromhex(s[3:]) if len(s) > 3 and len(s[3:]) % 2 == 0 else b""
            frames.append((can_id, data))
        return frames

    def request(self, payload, id_req, id_resp, espera=1.5):
        """
        Envia uma requisição de diagnóstico (ISO-TP) e remonta a resposta.
        'payload' = bytes do serviço (sem PCI). Retorna bytes da resposta (sem PCI)
        ou lança RuntimeError em resposta negativa (0x7F).
        """
        self.set_header(id_req)
        payload = bytes(payload)
        if len(payload) <= 7:
            frame = bytes([len(payload)]) + payload
            frame = frame.ljust(8, b"\x00")
            txt = self.raw(frame.hex().upper(), espera)
        else:
            # Multi-frame: First Frame + Consecutive Frames
            ff = bytes([0x10 | ((len(payload) >> 8) & 0x0F), len(payload) & 0xFF]) + payload[:6]
            self.raw(ff.hex().upper().ljust(16, "0"), 0.3)  # ECU responde com Flow Control
            rest = payload[6:]
            seq = 1
            while rest:
                cf = bytes([0x20 | (seq & 0x0F)]) + rest[:7]
                cf = cf.ljust(8, b"\x00")
                self.raw(cf.hex().upper(), 0.2)
                rest = rest[7:]
                seq += 1
            txt = self.raw("", espera)  # lê a resposta final

        return self._remontar_isotp(self._frames_rx(txt), id_resp)

    def _remontar_isotp(self, frames, id_resp):
        dados = bytearray()
        total = None
        for can_id, d in frames:
            if id_resp is not None and can_id != id_resp:
                continue
            if not d:
                continue
            pci = d[0] >> 4
            if pci == 0:          # Single Frame
                n = d[0] & 0x0F
                resp = d[1:1 + n]
                self._checa_negativo(resp)
                return bytes(resp)
            elif pci == 1:        # First Frame
                total = ((d[0] & 0x0F) << 8) | d[1]
                dados += d[2:]
                self.raw("3000", 0.2)  # envia Flow Control: Continue
            elif pci == 2:        # Consecutive Frame
                dados += d[1:]
        if total is not None:
            resp = bytes(dados[:total])
            self._checa_negativo(resp)
            return resp
        return b""

    @staticmethod
    def _checa_negativo(resp):
        if len(resp) >= 3 and resp[0] == 0x7F:
            raise RuntimeError("Resposta negativa do módulo: serviço 0x%02X, código 0x%02X"
                               % (resp[1], resp[2]))

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────
#  Lógica da configuração (usa a "receita" específica do carro)
# ─────────────────────────────────────────────────────────────────────────
def ler_bloco_config(elm, r):
    """Lê o bloco de configuração do IPC conforme a receita. Pode falhar se a
    receita ainda não estiver preenchida."""
    if not r.requisicao_leitura:
        raise RuntimeError("recipe.requisicao_leitura ainda DESCONHECIDA — "
                           "não há como ler a config sem verificar antes.")
    if r.sessao_diagnostica:
        elm.request(r.sessao_diagnostica, r.id_requisicao, r.id_resposta)
    resp = elm.request(r.requisicao_leitura, r.id_requisicao, r.id_resposta)
    return resp[r.offset_resposta_dados:]


def decodificar_temp(bloco, r):
    if r.byte_offset_temp < 0 or r.bit_temp < 0:
        return "desconhecido (receita não verificada)"
    if r.byte_offset_temp >= len(bloco):
        return "offset fora do bloco"
    bit = (bloco[r.byte_offset_temp] >> r.bit_temp) & 1
    real = bool(bit) == r.bit_set_significa_real
    return "REAL" if real else "SIMULADA"


def salvar_backup(bloco, sufixo=""):
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    nome = "backup_ipc_%s%s.bin" % (ts, sufixo)
    with open(nome, "wb") as f:
        f.write(bloco)
    print("  Backup salvo em: %s  (%d bytes)" % (nome, len(bloco)))
    return nome


# ─────────────────────────────────────────────────────────────────────────
#  Comandos de linha de comando
# ─────────────────────────────────────────────────────────────────────────
def cmd_scan(args, r):
    elm = Elm327(r.porta, r.baud, debug=True)
    try:
        prot = r.protocolo_ms if r.usar_ms_can else r.protocolo_hs
        elm.init(prot)
        print("\nAdaptador:", elm.raw("ATI").strip())
        print("Protocolo:", elm.raw("ATDP").strip())
        print("\nTentando falar com o IPC (id 0x%03X) via sessão padrão..." % r.id_requisicao)
        try:
            resp = elm.request([0x3E], r.id_requisicao, r.id_resposta)  # TesterPresent
            print("Resposta do IPC:", resp.hex().upper() or "(vazio)")
        except Exception as e:
            print("Sem resposta limpa do IPC:", e)
            print("-> Verifique o barramento (HS x MS-CAN) e o adaptador.")
    finally:
        elm.close()


def cmd_status(args, r):
    elm = Elm327(r.porta, r.baud, debug=args.debug)
    try:
        elm.init(r.protocolo_ms if r.usar_ms_can else r.protocolo_hs)
        bloco = ler_bloco_config(elm, r)
        print("Bloco de config do IPC:", bloco.hex().upper())
        print("Indicação de temperatura atual:", decodificar_temp(bloco, r))
    finally:
        elm.close()


def _set_temp(args, r, alvo_real):
    if not recipe_mod.VERIFICADO:
        print("RECUSADO: recipe.VERIFICADO = False.")
        print("A receita de gravação ainda não foi confirmada para o seu carro.")
        print("Gravar agora poderia corromper o painel. Veja o README (seção")
        print("'Como gerar a receita') para capturar a sequência do ELM-FF2.")
        return 2
    elm = Elm327(r.porta, r.baud, debug=args.debug)
    try:
        elm.init(r.protocolo_ms if r.usar_ms_can else r.protocolo_hs)
        bloco = bytearray(ler_bloco_config(elm, r))
        print("Atual:", decodificar_temp(bloco, r), "->", bloco.hex().upper())
        salvar_backup(bytes(bloco), "_antes")
        atual_real = decodificar_temp(bloco, r) == "REAL"
        if atual_real == alvo_real:
            print("Já está no estado desejado. Nada a fazer.")
            return 0
        # Inverte exatamente 1 bit
        bit_desejado = 1 if (alvo_real == r.bit_set_significa_real) else 0
        if bit_desejado:
            bloco[r.byte_offset_temp] |= (1 << r.bit_temp)
        else:
            bloco[r.byte_offset_temp] &= ~(1 << r.bit_temp)
        resp = input("Gravar novo bloco %s ? (digite SIM) " % bloco.hex().upper())
        if resp.strip() != "SIM":
            print("Cancelado.")
            return 1
        gravar_bloco_config(elm, r, bytes(bloco))
        # Relê e confere
        conf = ler_bloco_config(elm, r)
        print("Depois:", decodificar_temp(conf, r), "->", bytes(conf).hex().upper())
    finally:
        elm.close()
    return 0


def gravar_bloco_config(elm, r, bloco):
    """Grava o bloco (com security access e checksum conforme a receita)."""
    if r.sessao_diagnostica:
        elm.request(r.sessao_diagnostica, r.id_requisicao, r.id_resposta)
    if r.requer_security_access:
        if r.seed_key_algoritmo is None:
            raise RuntimeError("Security Access exigido mas algoritmo seed->key DESCONHECIDO.")
        seed = elm.request(r.security_request_seed, r.id_requisicao, r.id_resposta)[1:]
        key = r.seed_key_algoritmo(bytes(seed))
        elm.request(tuple(r.security_send_key) + tuple(key), r.id_requisicao, r.id_resposta)
    if not r.requisicao_escrita:
        raise RuntimeError("recipe.requisicao_escrita DESCONHECIDA.")
    payload = tuple(r.requisicao_escrita) + tuple(bloco)
    elm.request(payload, r.id_requisicao, r.id_resposta)


def cmd_parse_capture(args, r):
    """Lê um log serial do ELM-FF2 e reconstrói as mensagens de diagnóstico
    (ISO-TP), rotula os serviços e tenta deduzir o byte/bit alterado — para
    preencher o recipe.py com valores REAIS do seu carro."""
    import capture
    with open(args.arquivo, "r", encoding="utf-8", errors="replace") as f:
        texto = f.read()
    eventos = capture.analisar(texto)
    if not eventos:
        print("Nenhuma mensagem de diagnóstico reconhecida. Veja o formato "
              "esperado no topo de capture.py / no README.")
        return 1
    capture.resumir(eventos)


def main():
    p = argparse.ArgumentParser(description="Focus Mk2 — corrige temperatura do painel (sim->real)")
    p.add_argument("--porta", help="porta serial (ex.: COM3, /dev/ttyUSB0)")
    p.add_argument("--baud", type=int, help="baud (38400/115200)")
    p.add_argument("--debug", action="store_true", help="mostra tráfego ELM327")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan", help="testa adaptador e contato com o IPC")
    st = sub.add_parser("status", help="lê e mostra a config atual de temperatura")
    # SUPPRESS: sem isso, o default False do subcomando apaga o --debug global
    st.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)
    sr = sub.add_parser("set-real", help="muda para temperatura REAL (travado até verificar)")
    sr.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)
    ss = sub.add_parser("set-sim", help="volta para temperatura SIMULADA (travado até verificar)")
    ss.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)
    pc = sub.add_parser("parse-capture", help="analisa um log serial do ELM-FF2")
    pc.add_argument("arquivo")

    args = p.parse_args()
    r = recipe_mod.recipe_padrao()
    if getattr(args, "porta", None):
        r.porta = args.porta
    if getattr(args, "baud", None):
        r.baud = args.baud

    if args.cmd == "scan":
        return cmd_scan(args, r)
    if args.cmd == "status":
        return cmd_status(args, r)
    if args.cmd == "set-real":
        return _set_temp(args, r, alvo_real=True)
    if args.cmd == "set-sim":
        return _set_temp(args, r, alvo_real=False)
    if args.cmd == "parse-capture":
        return cmd_parse_capture(args, r)


if __name__ == "__main__":
    sys.exit(main() or 0)
