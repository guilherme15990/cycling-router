# Changelog

Todas as mudanças relevantes deste projeto são registradas aqui.

O projeto segue [Versionamento Semântico](https://semver.org/lang/pt-BR/)
(SemVer). A versão pública está em `api.__version__`.

Política de estabilidade:

- enquanto a versão principal for `0` (`0.y.z`), a API pública é considerada
  **utilizável e estável na prática**, mas correções e ajustes incompatíveis
  podem ocorrer em versões **menores**; em cada uma, as quebras são listadas
  neste changelog;
- a partir de `1.0.0`, mudanças incompatíveis e remoções só ocorrem em versões
  **maiores**; novos recursos em versões menores; correções em versões de
  patch;
- entram na garantia de API pública apenas os nomes exportados em
  `api.__all__` (ver [`docs/api.md`](docs/api.md)). Módulos internos, funções
  com prefixo `_` e atributos privados podem mudar sem aviso.

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/).
Versões anteriores a 0.11.0 não tiveram changelog mantido.

## [0.11.0] - 2026-11-10

### Adicionado

- **Perfil `Elétrico`** (`electric`): objetivos Pareto `(energia_mecânica,
  tempo)`, com viés para a rota de menor consumo. O perfil não altera a física.
- **Modelo energético genérico** (`physical.energy_model`): converte energia
  mecânica na roda em energia elétrica (`E_elétrica ≈ E_mec / η`, em J e Wh),
  com níveis `generic`, `personalized` e `calibrated`. Parâmetros de referência
  internos, sem dados de marca/modelo/bateria.
- **Bateria opcional** (`BatteryConfig`, `BatteryFeasibility`, `assess_battery`):
  viabilidade ("dá para chegar?"), reserva e percentual na chegada. Sem bateria
  não há autonomia nem percentual.
- **Estimativa energética pós-seleção** (`estimate_route_energy`,
  `estimate_routes_energy`, `RouteEnergyEstimate`), exposta em
  `ProfileSearchResponse.energy` (alinhada às rotas por índice).
- **Campos opcionais** em `ProfileSearchRequest`: `energy_model` e `battery`.
- **Tipos inline (PEP 561)**: marcadores `py.typed` nos pacotes e configuração de
  empacotamento.
- **Documentação**: [`docs/quickstart.md`](docs/quickstart.md) (3 receitas),
  [`docs/api.md`](docs/api.md) (referência com assinaturas geradas por
  introspecção via `scripts/generate_api_reference.py`) e este changelog.

### Alterado

- Docstrings de referência (estilo Google, com `Args`/`Returns`/`Raises`/
  `Example`) nos pontos de entrada das camadas públicas.
- `api.__all__` reagrupado por camada (com comentários), sem mudança de
  conteúdo; a fachada ganhou um mapa das camadas no docstring do módulo.
- Anotações de tipo completadas em `rank_candidates`, `rank_routes`,
  `select_routes`, `select_from_result`, `order_routes` e `search_profile`.
- Versão elevada para `0.11.0` (`pyproject.toml` e `api.__version__`).

### Corrigido

- Docstring de `surface_priority` (era a única função pública sem descrição).
- Docstring de `PhysicalTraversal.traverse` sobre a potência padrão (usa
  `cyclist.default_power_w`, não `sustainable_power_w`).
