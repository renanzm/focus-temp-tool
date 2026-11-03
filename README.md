# focus-temp-tool

Ferramenta mínima e open-source para trocar a indicação de **temperatura do
motor no painel** do **Ford Focus Mk2 (C307)** de **simulada** para **real**,
usando um adaptador **ELM327** na porta OBD-II.

Os Focus brasileiros saem de fábrica com a temperatura **simulada** (o ponteiro
fica "preso" no meio). O painel (módulo **IPC**) tem um bit de configuração que
troca para a leitura **real** do sensor. Ferramentas como o ELM-FF2 fazem isso —
mas são difíceis de usar e cheias de opções que ninguém quer. Este projeto faz
**só isso**, com segurança.

---

## ⚠️ Status atual: LEITURA liberada, GRAVAÇÃO travada

Gravar configuração num módulo do carro pode **corromper o painel** se o byte,
o bit, o checksum ou o Security Access estiverem errados. Por isso o programa
**só grava quando a "receita" (`recipe.py`) estiver confirmada** para o Focus
Mk2 (flag `VERIFICADO = True`).

Hoje essa receita **ainda não está verificada**. O que já funciona:

| Comando          | Faz                                                  | Estado |
|------------------|------------------------------------------------------|--------|
| `scan`           | Testa o adaptador e o contato com o IPC              | ✅ pronto |
| `status`         | Lê e mostra a config de temperatura                 | ⏳ precisa dos parâmetros de leitura |
| `set-real`       | Muda para temperatura real                          | 🔒 travado até verificar |
| `set-sim`        | Volta para simulada                                 | 🔒 travado até verificar |
| `parse-capture`  | Ajuda a extrair a receita de um log do ELM-FF2      | ✅ pronto |

Isso é proposital: **ninguém deveria gravar bytes "no chute" no painel.**

---

## O que a engenharia reversa mostrou

O ELM-FF2 é freeware (sem cláusula anti-RE), então analisá-lo é legítimo. Ele
foi **decompilado por completo no Ghidra** (3498 funções). Conclusões:

- É Delphi; fala com o ELM327 por **porta serial Win32** (`CreateFileA`/
  `WriteFile`/`ReadFile`), montando os comandos `AT` **caractere a caractere**
  (por isso não aparecem como texto no binário);
- A tabela de opções está no recurso de formulário (DFM): `IPC34` = temperatura
  simulada, `IPC36` = real;
- O banco do ELMConfig (`frw.dat`) é **criptografado**.

O que a análise estática **não** entrega com segurança neste binário (stripped,
bytes de protocolo gerados em runtime a partir de tabelas): os **IDs CAN**, a
**sequência de serviços**, **se há Security Access** e seu algoritmo, o
**offset/bit** real e o **checksum**. E mesmo que entregasse, **não dá para
validar sem o carro** — errar arrisca o painel.

Por isso a fonte de verdade **confiável** é uma **captura serial** do ELM-FF2
fazendo a troca no seu carro: determinística e idêntica ao seu IPC/firmware. O
módulo [`capture.py`](capture.py) converte essa captura na receita
automaticamente (decodifica os serviços, detecta Security Access e deduz o
byte/bit pelo diff entre o bloco lido e o gravado):

```
$ python focus_temp.py parse-capture captura.txt
  REQ  0x720  svc=ReadDataByLocalId    dados=2101
  RESP 0x728  svc=ReadDataByLocalId    dados=6101AABBCCDD04
  REQ  0x720  svc=SecurityAccess       dados=2701
  ...
  REQ  0x720  svc=WriteDataByLocalId   dados=3B01AABBCCDD14
Security Access (0x27) presente? SIM
Tentando deduzir byte/bit alterado (leitura x escrita):
  byte_offset=5  bit=4  (0x04 -> 0x14)
```

---

## Como gerar a receita (captura do ELM-FF2)

Você faz isso **uma vez**; depois o `recipe.py` fica pronto para toda a comunidade.

1. Instale um par de portas virtuais (**com0com**) ligando `COM3 <-> COM4`.
2. Aponte o **ELM-FF2** para uma das portas e um **logger serial**
   (ex.: HHD Serial Monitor, ou `pyserial` em modo sniff) para a outra, ou use
   um monitor que grave o tráfego real do adaptador.
3. No carro, com o ELM-FF2, faça **apenas** a troca de temperatura simulada→real
   (como você já sabe fazer) enquanto o log grava.
4. Salve o log em texto e rode:
   ```bash
   python focus_temp.py parse-capture meu_log.txt
   ```
5. Abra uma *issue* com esse log (sem VIN/dados pessoais). Com ele dá para
   preencher em `recipe.py`: IDs CAN, sessão, **se há Security Access** e o
   algoritmo seed→key, o serviço de leitura/escrita, o **byte/bit** da opção e
   o **checksum**. Aí a flag `VERIFICADO` vira `True`.

> A engenharia reversa do ELM-FF2 no Ghidra pode **corroborar** esses valores,
> mas a captura é o que torna a gravação segura.

---

## Adaptador (ponto crítico no Mk2)

No Focus Mk2 o **IPC normalmente fica na rede MS-CAN (125 kbit/s)**, não na
HS-CAN (500 kbit/s) do motor. Um ELM327 USB simples costuma **só** enxergar a
HS-CAN e **não alcança o painel**. Use um adaptador com **chave HS/MS-CAN** ou
multiplexado (ex.: OBDLink EX, vLinker FS, ou ELM327 com switch MS/HS-CAN).

---

## Instalação e uso

```bash
pip install -r requirements.txt
python focus_temp.py --porta COM3 scan
python focus_temp.py --porta COM3 status
```

Requisitos: Python 3.8+ e `pyserial`.

---

## Segurança / isenção

- Use por **sua conta e risco**. Projeto sem vínculo com a Ford.
- Faça a gravação com **carregador de bateria** (tensão estável).
- O programa **sempre** salva um backup do bloco antes de gravar e relê depois.
- Desligue/ligue a ignição entre operações, se o módulo pedir.

## Licença

MIT — veja [LICENSE](LICENSE). Contribuições (capturas, confirmação de valores,
suporte a outros módulos) são bem-vindas.
