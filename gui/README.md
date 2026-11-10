# GUI de teste — roteamento ciclístico

Aplicação **desktop simples** para rotear e testar a engine sem
escrever código: mostra o **mapa**, deixa clicar origem/destino, roda os cinco
perfis (incluindo o **Elétrico**, com energia estimada em Wh) e plota a
**altimetria** consultada de forma **keyless** (tiles Terrarium).

Fica numa pasta separada (`gui/`), fora do pacote `src`: **não** é
empacotada nem descoberta pelos testes do projeto.

## Requisitos

Só a biblioteca padrão — **sem PIL, requests, numpy ou matplotlib**:

- `tkinter` (9.0) para a interface;
- `urllib` (stdlib) para baixar tiles;
- `zlib` + um decodificador PNG em Python puro para ler os tiles Terrarium.

Roda no Python que já executa a engine (testado no 3.15 com tkinter 9.0).

## Como executar

A partir da raiz do projeto:

```powershell
& "$env:USERPROFILE\scoop\apps\python\current\python.exe" gui\run_gui.py
```

Opcionalmente passe um grafo:

```powershell
python gui\run_gui.py caminho\para\grafo.json
```

Sem argumento, tenta abrir `data/se.json`. Se os módulos da engine não estiverem
instalados, o `run_gui.py` adiciona `src/` ao `sys.path` automaticamente.

Também funciona rodar o módulo direto (ele reenvia para o pacote sozinho):

```powershell
python gui\routegui\app.py
```

## Uso

1. **Carregar** o grafo (JSON no formato `roteamento.cycling-graph`).
2. No mapa: **1º clique = origem (A)**, **2º clique = destino (B)**. A busca
   dispara sozinha ao definir os dois.
3. Ajuste **perfil**, **N rotas** e **v0** na barra superior; os parâmetros
   físicos (massa, potência, teto de velocidade) ficam no painel lateral. No
   perfil **Elétrico**, a coluna "energia (Wh)" mostra o consumo estimado
   (modelo genérico; sem bateria configurada não há autonomia nem percentual).
4. O painel mostra as rotas selecionadas; clicar numa rota **destaca** no mapa
   e **recalcula a altimetria** daquela rota.

Interação no mapa:

- **arrastar** = pan;
- **roda do mouse** = zoom;
- **clique** = define origem/destino.

## Altimetria keyless (Terrarium)

O perfil de elevação **não** usa API com chave. Baixamos tiles raster
Terrarium e lemos a altura embutida no canal RGB:

```
elevação_m = (R * 256 + G + B / 256) - 32768
```

- URL: `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png`
- `zoom` da altimetria é configurável no painel (padrão 12, ~30 m/px).
- A decodificação do PNG é feita com `zlib` (`IHDR`/`IDAT` + inflate +
  "unfilter" das 5 estratégias de filtro), já que não há PIL/numpy.

O perfil é amostrado a cada 25 m ao longo da geometria da rota
(`elevation.build_elevation_profile`) e desenhado em um
`tk.Canvas`.

## Mapa

- Fundo: tiles raster do **OpenStreetMap** (`tile.openstreetmap.org`).
- Projeção **Web Mercator** própria (`routegui/proj.py`).
- Renderização sem *compositing*: cada tile vira um `tk.PhotoImage` colocado no
  `Canvas`; rotas e marcadores são itens vetoriais por cima.
- Tiles baixados em threads de trabalho e servidos de um **cache em disco**
  (`.tilecache/`, ao lado da GUI).

Os tiles são baixados na rede na primeira vez. Sem internet, o mapa fica vazio
e a altimetria mostra "sem dados" — mas a busca e a GUI continuam funcionando.

## Estrutura

```
gui/
  run_gui.py                 # ponto de entrada
  routegui/
    proj.py                  # Web Mercator + viewport (puro, testável)
    tiles.py                 # camadas de tiles + cache em disco (urllib)
    terrain.py               # decode PNG (zlib) + provedor Terrarium
    engine_bridge.py         # grafo, modelo físico, snapping e search_profile
    map_canvas.py            # Canvas com tiles, rotas, marcadores, pan/zoom
    elevation_plot.py        # gráfico de altimetria (tk.Canvas)
    app.py                   # janela, controles e orquestração
  tests/                     # testes puros (sem Tk/rede) + integração
```

A GUI só conhece estruturas simples de `engine_bridge` (`GuiRoute`,
`RouteComputation`). O pipeline real é o mesmo da biblioteca:

```
build_query_graph -> MultiObjectiveAStar -> seleção por perfil -> explicação
```

O perfil **não** altera a física: a busca e a seleção apenas leem as métricas.

## Testes

Testes puros (projeção, decodificação PNG, codificação Terrarium) e um teste de
integração com `data/se.json`, sem abrir janela:

```powershell
python -m pytest gui\tests
```

## Observações

- A pasta `gui/` **não** é incluída por `[tool.setuptools.packages.find]`
  (`where=["src"]`) nem por `pytest` (`testpaths=["tests"]`). Para rodar os
  testes da GUI, passe o caminho explicitamente.
- `PhotoImage` exige PNG válido; tiles corrompidos são ignorados.
- O cache fica em `gui/.tilecache/` (no `.gitignore`). Apague para forçar novo
  download.
