# focus-temp-tool

Uma ferramenta pequena e open source para o **Ford Focus Mk2 (C307)** com um
único objetivo: fazer o ponteiro de temperatura do painel mostrar a temperatura
**real** do motor, em vez da **simulada**.

> **Importante: hoje esta ferramenta ainda não faz a troca no carro.**
> A gravação está travada de propósito até alguém confirmar os valores certos a
> partir de um carro real, e nada aqui foi testado em um carro ainda. Se você quer
> fazer a troca agora, use o ELM-FF2. Se quer ajudar a tirar o projeto do papel,
> veja [Como ajudar](#como-ajudar-capturando-a-troca).

## Qual é o problema?

Os Focus brasileiros saem de fábrica com a temperatura **simulada**: o ponteiro
fica parado no meio e não mostra o que o motor está fazendo de verdade. O painel
tem uma configuração interna que passa a usar o sensor real.

O ELM-FF2, um programa gratuito feito por um clube russo de donos de Focus, já
consegue mudar isso. Só que ele é difícil de usar e cheio de opções que a maioria
das pessoas nunca vai precisar. A ideia aqui é fazer **só essa troca**, com
poucos comandos e com segurança.

## Em que pé está

| Comando         | O que faz                                          | Situação hoje |
|-----------------|----------------------------------------------------|---------------|
| `parse-capture` | Analisa um log do ELM-FF2 e ajuda a achar os valores | ✅ Funciona; testado só com logs de exemplo |
| `scan`          | Testa o adaptador e tenta falar com o painel       | 🧪 Pronto, mas ainda não testado em carro |
| `status`        | Mostra se a temperatura está real ou simulada      | ⏳ Ainda não funciona: falta o comando de leitura |
| `set-real`      | Muda para temperatura real                         | 🔒 Travado |
| `set-sim`       | Volta para temperatura simulada                    | 🔒 Travado |

### Por que a gravação está travada?

Gravar um valor errado pode **corromper a configuração do painel**. Os dados
específicos do carro ficam em [`recipe.py`](recipe.py), a "receita", e o programa
recusa qualquer gravação enquanto `VERIFICADO = False`. Hoje a receita tem só
palpites ou campos em branco.

Para destravar, falta confirmar em um carro real:

- [ ] Os IDs CAN do painel (hoje `0x720` e `0x728` são apenas palpites)
- [ ] Os comandos de sessão, leitura e escrita
- [ ] Se o painel exige Security Access e, nesse caso, qual é o algoritmo
- [ ] O byte e o bit exatos da opção de temperatura
- [ ] Se existe checksum e como ele é calculado. **O código ainda não calcula
      checksum**, então isso teria que ser implementado se ele for necessário

## O que você precisa

- **Python 3.8 ou mais novo**
- **Um adaptador ELM327 que alcance a rede MS-CAN.** Este é o ponto que mais
  costuma dar errado.

No Focus Mk2 o painel normalmente fica na rede **MS-CAN** (125 kbit/s), e não na
HS-CAN (500 kbit/s) usada pelo motor. Um ELM327 USB simples costuma enxergar só a
HS-CAN e não chega ao painel. Procure um adaptador com chave HS/MS-CAN ou com
troca automática de rede, como o OBDLink EX, o vLinker FS ou um ELM327 com chave.

A seleção de MS-CAN no código ainda é provisória, então talvez você precise
ajustar `protocolo_ms` em [`recipe.py`](recipe.py) para o seu adaptador.

## Instalação

```bash
git clone https://github.com/renanzm/focus-temp-tool.git
```

```bash
cd focus-temp-tool
```

```bash
pip install -r requirements.txt
```

## Como usar

Troque `COM3` pela porta do seu adaptador (no Linux, algo como `/dev/ttyUSB0`).
A opção `--porta` vem **antes** do comando.

Testar o adaptador e o contato com o painel (só leitura; o tráfego aparece na tela):

```bash
python focus_temp.py --porta COM3 scan
```

Analisar um log capturado do ELM-FF2 (não precisa do carro):

```bash
python focus_temp.py parse-capture captura.txt
```

Ver todas as opções:

```bash
python focus_temp.py --help
```

## Como ajudar: capturando a troca

Esta é a contribuição que mais faz diferença. Basta **uma captura boa** do
ELM-FF2 fazendo a troca em um carro real para preencher quase toda a receita.

1. **Grave o tráfego da porta serial.** O jeito mais simples é usar um monitor de
   porta serial (como o HHD Serial Monitor) na porta do adaptador. Com portas
   virtuais (com0com), você também precisa de uma ponte até a porta real do
   adaptador (como o hub4com), senão os comandos não chegam ao carro.
2. **No ELM-FF2, faça apenas a troca de temperatura** enquanto o log grava. Pode
   ser em qualquer sentido: o que importa é a captura mostrar a leitura e a
   gravação do bloco de configuração. Se o seu carro já está em "real", capture a
   volta para "simulada" e depois retorne.
3. **Salve o log como `captura.txt`**, no formato descrito abaixo.
4. **Rode a análise:** `python focus_temp.py parse-capture captura.txt`
5. **Apague o VIN e outros dados pessoais** e abra uma
   [issue](https://github.com/renanzm/focus-temp-tool/issues) com o log e a
   saída do comando, informando o ano do carro, o motor e o adaptador.

### Formato do log

Cada linha precisa começar com a direção do tráfego: `>>`, `TX`, `SEND` ou `->`
para o que foi enviado, e `<<`, `RX`, `RECV` ou `<-` para o que foi recebido.

### Exemplo

> **Os valores abaixo são fictícios** e servem só para mostrar o formato.
> **Não os use no seu carro.**

```text
>> ATSH720
<< OK
>> 2101
<< 728 06 61 01 AA BB CC 04
>> 2701
<< 728 04 67 01 12 34
>> 3B01AABBCC14
<< 728 02 7B 01
```

Saída do `parse-capture` para esse log:

```text
Linha do tempo de diagnóstico:

  REQ  0x720  svc=ReadDataByLocalId  dados=2101
  RESP 0x728  svc=ReadDataByLocalId  dados=6101AABBCC04
  REQ  0x720  svc=SecurityAccess  dados=2701
  RESP 0x728  svc=SecurityAccess  dados=67011234
  REQ  0x720  svc=WriteDataByLocalId  dados=3B01AABBCC14
  RESP 0x728  svc=WriteDataByLocalId  dados=7B01

Security Access (0x27) presente? SIM

Tentando deduzir byte/bit alterado (leitura x escrita):
  byte_offset=4  bit=4  (0x04 -> 0x14)
```

O `byte_offset` é contado a partir do byte logo depois do código do serviço. Ele
é uma **pista para conferir**, não um valor pronto para gravar.

## O que já se sabe sobre o ELM-FF2

O ELM-FF2 foi analisado para entender como ele faz a troca:

- É um programa em Delphi que fala com o ELM327 pela porta serial do Windows.
- As opções do painel aparecem como `IPC34` (temperatura simulada) e `IPC36`
  (temperatura real). O próprio programa avisa que a leitura real não funciona
  sem o sensor físico.
- Os bytes do protocolo são montados durante a execução. A análise estática não
  revelou com segurança os IDs CAN, o Security Access, o byte/bit nem o checksum.
- Mesmo que revelasse, não daria para validar sem um carro. Por isso a captura é a
  fonte de verdade deste projeto.

Este repositório **não contém código, binários nem arquivos do ELM-FF2**. O
projeto não tem vínculo com os autores dele. A cópia analisada não trazia licença
nem termos de uso.

## Como o código está organizado

| Arquivo                        | Para que serve |
|--------------------------------|----------------|
| [`focus_temp.py`](focus_temp.py) | O programa: comandos, comunicação com o ELM327 e ISO-TP |
| [`recipe.py`](recipe.py)       | A "receita": tudo que é específico do carro, incluindo a trava `VERIFICADO` |
| [`capture.py`](capture.py)     | A análise dos logs capturados |

## Segurança

- **Use por sua conta e risco.** Este projeto não tem vínculo com a Ford.
- **Nunca grave valores "no chute"** e não mude `VERIFICADO` para `True` sem ter
  confirmado todos os itens da lista acima.
- **Use um carregador de bateria** em qualquer gravação: queda de tensão durante a
  escrita pode corromper o módulo. Isso vale também ao usar o ELM-FF2.
- **Depois que a gravação for liberada**, o programa salva um backup do bloco antes
  de gravar, pede confirmação e relê o bloco no final. Ainda não existe comando
  para restaurar esse backup.
- **Seus dados ficam fora do Git.** O `.gitignore` já ignora `captura*.txt`,
  `*.log` e `backup_ipc_*.bin`, que podem conter dados do seu carro.

## Licença

[MIT](LICENSE). Capturas, confirmações de valores e correções são muito bem-vindas.
