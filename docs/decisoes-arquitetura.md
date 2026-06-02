# Decisões de Arquitectura

Documento vivo das decisões tomadas em conjunto. Cada entrada tem **decisão**, **alternativas consideradas**, **motivo da escolha** e **implicações**.

## ADR-001 — Versão canónica do código existente

**Data**: 2026-05-27
**Decisão**: `CODE/PFC_V3.1/` é a versão de referência matemática. As outras (`NPP_V1.1_Flores/`, `PFC_V2.0/`, `Projeto/`, `PROJETO/` na raiz) são histórico — não tocar.
**Motivo**: V3.1 é a entregue/avaliada; alinhada com o Relatório Final-P33.
**Implicações**: leitura de código para extracção de fórmulas concentra-se em `PFC_V3.1/NPP_CALC_PROJ/*_CALC/`; o código refactorizado nasce numa árvore nova, a definir.

## ADR-002 — Estratégia para a web

**Data**: 2026-05-27
**Decisão**: **(A) Pré-processamento offline → COG/JSON estáticos**, servidos pela Vercel sem Python em runtime.
**Alternativas consideradas**:
- (B) API Python em container (FastAPI fora da Vercel) — custo recorrente de infra; complexidade de deploy.
- (C) Híbrido — overkill para o âmbito actual.
**Motivo**: simplicidade, custo zero de runtime, sem dependências GDAL/rasterio no bundle Vercel (que tem limite duro de 50–250 MB).
**Implicações**: tudo o que envolva `snappy`, `rasterio`, `GDAL`, GEE Python SDK corre offline; output é COG + JSON; frontend consome via Leaflet/MapLibre + georaster browser-side.

## ADR-003 — Automação assíncrona via GitHub Actions

**Data**: 2026-05-27
**Decisão**: Pipeline 100% autónomo num **GitHub Actions Cron mensal**. Sem servidor sempre-ligado.
**Fluxo**:
1. Cron dispara no dia 1 de cada mês.
2. Script Python: autentica em GEE (service account em secret), descarrega máscara Dynamic World do mês anterior, descarrega bandas Sentinel-2 / Sentinel-3 via Sentinel Hub API, descarrega CAMS time-series.
3. Corre CASA, gera COG (NPP, NPP_C, NPP_CO2) + JSON (relatório por região).
4. Commita outputs no repo (ou faz upload para storage — ver ADR-005).
5. Vercel detecta o push, redeploy automático, conteúdo novo disponível em minutos.
**Motivo**: dados sempre frescos, zero manutenção manual, zero custo de infra de runtime.
**Decisões dependentes**: ADR-005 (storage), ADR-006 (autenticação GEE em CI).

## ADR-004 — Substituição de ESA WorldCover por Dynamic World

**Data**: 2026-05-27
**Decisão**: A máscara de vegetação e a atribuição de ε_max passam a usar **Google Dynamic World (`GOOGLE/DYNAMICWORLD/V1`)** via Earth Engine, consultado **no GitHub Actions Cron**, não em runtime.
**Motivo**: dataset near-real-time (atualização ~5 dias), 9 classes, 10 m de resolução, alinhado com o objectivo "100% atualizado sem intervenção manual".
**Mapeamento Dynamic World → ε_max** (default Xu 2023):
- `trees` → 1.106 g C/MJ (média BPLUT forest)
- `shrub_and_scrub` → 1.061
- `grass` → 0.86
- `crops` → 1.044
- `flooded_vegetation` → 0.86
- `built`, `water`, `bare`, `snow_and_ice` → 0 (máscara não-vegetação)
**Implicações**: substituir `Emax_CALC.py` por chamada GEE; cache local opcional de máscaras já calculadas.

## ADR-005 — Storage dos outputs COG e JSON

**Data**: 2026-05-27 (revisto na mesma data)
**Decisão**: **TODOS os outputs (COG + JSON) como assets de GitHub Releases**. Zero commits ao repo após Cron — repo permanece 100% código.
**Alternativa rejeitada**: commitar JSON em `public/latest/` com `[skip ci]`.
  - Problema: Vercel serve estáticos do *build*, não do filesystem em runtime. Com `[skip ci]` não há rebuild, logo o JSON novo *não chega ao utilizador*. Para chegar tem de haver rebuild — anula o ganho.
  - Outras alternativas: GitHub LFS (limites bandwidth), Vercel Blob / R2 (conta externa).
**Motivo**: limpo, sem custos, sem ciclos perversos de deploy, urls estáveis com CORS aberto.
**Implementação**:
- Cada execução mensal cria/atualiza uma release com tag `YYYY-MM` (ex.: `2026-05`).
- Assets por release:
  - `{region}_npp_co2.tif` (COG)
  - `{region}_npp_c.tif` (COG, opcional)
  - `{region}.json` (totais + metadata)
  - `index.json` (manifesto de regiões e status no mês)
- URLs estáveis:
  - `https://github.com/{user}/{repo}/releases/download/2026-05/oeiras_npp_co2.tif`
  - `https://github.com/{user}/{repo}/releases/download/2026-05/oeiras.json`
- Frontend descobre a release mais recente via API GitHub: `GET /repos/{user}/{repo}/releases/latest` (cache-friendly, 1 round-trip).
**Discovery sem chamar a API GitHub** (evita rate limit 60 req/h unauthenticated):
- Para o mês mais recente: URL pública directa `https://github.com/{user}/{repo}/releases/latest/download/{region}_npp_co2.tif` — redirecciona para o asset, sem passar pela API.
- Para meses específicos (time slider): `https://github.com/{user}/{repo}/releases/download/2026-04/oeiras.json`. URLs determinísticas; frontend monta a URL a partir da tag.
- **Lista de meses disponíveis**: ficheiro `releases.json` mantido numa **branch órfã `data`**.
  - **Default**: `https://raw.githubusercontent.com/{user}/{repo}/data/releases.json` (cache CDN Cloudflare ~5 min — aceitável para dados mensais).
  - **Alternativa NÃO recomendada como default**: jsDelivr (`https://cdn.jsdelivr.net/gh/{user}/{repo}@data/releases.json`) — cache agressivo até 24 h e purge manual via `https://purge.jsdelivr.net/`. Se for usado, **obrigatório cache-busting**: append de um query param time-bucketed, ex.: `?t=${Math.trunc(Date.now()/300000)}` (janela de 5 min). Sem isto, utilizadores podem ver o mês anterior por até um dia após o Cron correr.
- O workflow GHA, no fim de cada execução, faz `git push` à branch `data` com o `releases.json` atualizado. **A branch `data` é órfã (`git checkout --orphan data`) — sem história de código, só history de dados; nunca cruza com `main`**, logo Vercel ignora estes pushes (não há build hook para branches não-tracked).

**Implicações**: frontend faz, no boot, 1 fetch a `raw.githubusercontent.com/.../data/releases.json` (CDN-cached, ~50 KB no máximo). Daí em diante, todos os COGs e JSONs são URLs determinísticas. Zero chamadas à API GitHub. CORS OK (raw.githubusercontent.com serve `Access-Control-Allow-Origin: *`).

## ADR-006 — Autenticação Google Earth Engine em CI

**Data**: 2026-05-27
**Estado**: **pendente — criar conta GCP** (utilizador ainda não tem). Paralelizar com restante da Fase 4.
**Plano**:
1. Criar conta Google Cloud Platform (free tier).
2. Activar Earth Engine API e submeter pedido de acesso "non-commercial / research" (justificação: portefólio académico/profissional, dados Sentinel pública).
3. Criar service account dedicada (`earthengine-cron@<project>.iam.gserviceaccount.com`).
4. Gerar JSON key. Guardar em GitHub Secret `GEE_SERVICE_ACCOUNT_JSON`.
5. No workflow GHA: `ee.ServiceAccountCredentials(email, key_file)` → `ee.Initialize(credentials)`.
**Tempo estimado de aprovação Earth Engine**: dias a semanas (Google revê manualmente).
**Mitigação enquanto não há acesso**: implementar todo o pipeline com a máscara Dynamic World como TODO (interface definida, implementação stub que devolve uma máscara estática de fallback — o ESA WorldCover já em uso). Quando acesso EE chega, troca-se o stub pela chamada real.
**Implicações**: a Fase 4a pode avançar com interface bem definida; a implementação concreta da chamada GEE fica para depois da aprovação.

## ADR-006 — Autenticação GEE em CI (decisão pendente)

**Data**: aberto
**Opções**:
- Service account do Google Cloud → JSON em GitHub Secret → autenticação via `ee.ServiceAccountCredentials`.
- Limitação: precisa de aprovação da Google para "Earth Engine for non-commercial use" se for projeto académico/portefólio.
**Recomendação atual**: registar service account, pedir acesso EE non-commercial. Tempo estimado: dias a semanas para a aprovação.

## ADR-007 — Documentação científica separada do CLAUDE.md

**Data**: 2026-05-27
**Decisão**: `docs/` para tudo o que é científico/bibliográfico. CLAUDE.md fica operacional (regras, padrões, comandos, estrutura).
**Ficheiros**:
- `docs/casa-model.md` — derivação matemática operacional.
- `docs/literatura.md` — bibliografia comentada.
- `docs/decisoes-arquitetura.md` — este ficheiro (ADRs).
**Motivo**: CLAUDE.md sempre carregado em contexto, tem limite de ~200 linhas úteis. Documentação científica é load-on-demand.

## ADR-008 — Refactor é rewrite, não patch

**Data**: 2026-05-27
**Decisão**: o código em `CODE/PFC_V3.1/NPP_CALC_PROJ/*_CALC/` é fonte de **referência matemática apenas**. Versão refactorizada nasce numa árvore nova (a definir), com:
- Pacote Python instalável (`pyproject.toml`).
- Módulos coesos: `casa/{fpar.py, wsc.py, t_stress.py, sol.py, emax.py, npp.py}` + `pipeline.py` + `config/` + `cli.py`.
- Tests com `pytest` (sanity-checks de unidades, smoke-tests com dados reais).
- Sem `esa_snappy` em runtime — tudo `rasterio` após uma conversão SAFE→GeoTIFF única (ou via Sentinel Hub directamente em GeoTIFF).
- Sem caminhos relativos hardcoded — config central via env / argparse.
**Motivo**: o código actual tem bugs (PIL para GeoTIFFs, hack do último pixel, CRS hardcoded em WSC, `input()` interactivo, scripts top-level sem `__main__`, etc.) que justificam mais um rewrite do que um patch.

## ADR-009 — Parametrização por região e por tabela ε_max

**Data**: 2026-05-27
**Decisão**:
- `config/regions/{oeiras,lisboa,flores,...}.yml` — geometria WKT, população, emissões per capita, ponto-referência CAMS, opcionalmente `VAR_PCT_MES` específico.
- `config/epsilon_max/{xu2023,relatorio}.yml` — duas tabelas; pipeline lê a apontada por config global. Default = `xu2023` (rastreável); `relatorio` reproduz resultados publicados.
**Motivo**: emissões per capita variam por zona; ε_max ainda é decisão científica em aberto, queremos sensibilidade testável.

## ADR-011 — Schema canónico de cobertura do solo

**Data**: 2026-05-27
**Decisão**: o pipeline opera sobre um **schema canónico** interno de cobertura, independente da fonte (Dynamic World ou ESA WorldCover). Adaptadores convertem cada fonte para o schema antes do cálculo de ε_max.
**Motivo**: as duas fontes têm taxonomias incompatíveis (DW: strings/9 classes; ESA: int codes/11 classes LCCS). Mapear `ε_max` directo a partir de cada fonte duplica lógica e quebra o fallback do stub.
**Schema canónico** (UInt8, codificação interna):
| Código | Label | DW source | ESA WorldCover source |
|---|---|---|---|
| 0 | `non_vegetation` | `built`, `water`, `bare`, `snow_and_ice` | 50, 60, 70, 80, 100 |
| 1 | `trees` | `trees` | 10 |
| 2 | `shrub_and_scrub` | `shrub_and_scrub` | 20 |
| 3 | `grass` | `grass` | 30 |
| 4 | `crops` | `crops` | 40 |
| 5 | `flooded_vegetation` | `flooded_vegetation` | 90, 95 |
**Implementação**:
- Módulo `casa/landcover.py` com `dw_to_canonical()` e `esa_to_canonical()`. Vectorizados.
- `config/epsilon_max/{xu2023,relatorio}.yml` mapeiam **canonical → ε_max**, nunca DW/ESA directos.
- Acrescento de uma fonte nova no futuro = um adaptador novo, sem tocar no resto.

**Comportamento defensivo (obrigatório)** — adaptadores nunca devem lançar `KeyError` em runtime de produção:
- **Default = `non_vegetation` (código 0)** para qualquer valor não explicitamente mapeado (classes novas em versões futuras dos datasets, pixels de transição, artefactos).
- **NoData / NaN** mapeados também para `0`, sem propagar como NaN para downstream (NaN num código UInt8 não existe; precisamos garantir saída válida).
- Implementação preferida (NumPy, sem dicionários rígidos):
  ```python
  def dw_to_canonical(dw: np.ndarray) -> np.ndarray:
      out = np.zeros(dw.shape, dtype=np.uint8)  # default: non_vegetation
      out[dw == 1] = 1  # trees
      out[dw == 2] = 2  # grass  (DW codifica em ints; ver tabela acima)
      out[dw == 4] = 3  # crops
      out[dw == 5] = 2  # shrub_and_scrub  (ajustar aos códigos reais DW)
      out[dw == 3] = 5  # flooded_vegetation
      # tudo o resto fica em 0 por construção
      return out
  ```
- Pre-condição num teste unitário: passar `dw=999` ou `dw=NaN-equivalente` e verificar que sai `0`, não exceção.
- Logging: contar pixels que caíram no default e logar warning se `default_pct > 5%` (sinal de versão nova do dataset com classes que ainda não mapeámos).

## ADR-012 — Pipeline windowed end-to-end

**Data**: 2026-05-27
**Decisão**: todas as etapas do pipeline CASA (NDVI, FPAR, WSC, Tε, SOL, ε_max, NPP) operam **por janela** (`rasterio.windows.Window`), não sobre o raster completo. O orquestrador gera as janelas da grade comum (Sentinel-2 10 m) e itera.
**Motivo**: `WarpedVRT` lazy poupa RAM no upsampling 1 km → 10 m (Sentinel-3 LST), mas o ganho desaparece se a multiplicação final fizer `src.read(1)` sem `window=` — força a materialização de todos os rasters em RAM (~100 MB+ por região para Flores). Tem de ser windowed end-to-end.
**Implementação**:
- Cada função de cálculo CASA aceita `window: rasterio.windows.Window | None`. `None` = raster completo (modo "Oeiras pequeno", testes).
- Orquestrador (`pipeline.py`) gera janelas por `rasterio.windows.subdivide` ou loop manual em blocos de 1024×1024 ou 2048×2048 pixels da grade comum.
- Para cada janela: lê todos os inputs com `window=`, multiplica, escreve output com `window=`.
- Pico de memória por janela: ~48 MB (6 rasters × 4 MB para 1024×1024 float32 + output).
**Implicações**:
- Pipeline escala para Lisboa/Flores sem alterações.
- Testes unitários podem correr `window=None` (mais simples).
- Permite paralelizar janelas com `concurrent.futures` no futuro (não na primeira versão).

## ADR-013 — Novo repo `co2-casa` para o refactor

**Data**: 2026-05-28
**Decisão**: o refactor vive num **novo repo `co2-casa`**, não numa subpasta do actual. O repo actual (`PROJETO/`) fica como histórico arquivado.
**Motivo**: o repo actual tem .venv commitada, `.idea/`, `tempCodeRunnerFile.py`, 5 versões do código (V1.1_Flores, V2.0, V3.1, Projeto, PROJETO/raiz), inputs Sentinel binários no git, e várias pastas com PDFs de dados. Carregar este lastro num clean refactor é trazer ruído. Clean slate é mais rápido.
**Implicações**:
- Migrar para `co2-casa` apenas: `CLAUDE.md`, `docs/`, `tools/extract_pdf.py` + `tools/literature/`, geometria/WKT de Oeiras, `data/sol/ghi_base.tif`.
- `PROJETO/` continua a existir como referência matemática (consultável) mas não é tocado.
- Deploy Vercel aponta para `co2-casa/frontend/`.

## ADR-014 — Packaging com `uv` + `pyproject.toml`

**Data**: 2026-05-28
**Decisão**: `uv` (Astral) como gestor de pacotes + venv. `pyproject.toml` PEP 517 standard com `uv.lock` versionado.
**Motivo**: install reprodutível e rápido (Rust-based, 10–100× pip); lockfile real garante determinismo em CI; GHA tem action oficial `astral-sh/setup-uv@v3`. Standards-compatible — se quiser trocar depois para pip ou poetry, o `pyproject.toml` é portável.
**Implicações**:
- `pyproject.toml` declara `[project]`, `[project.scripts]` (entrypoint CLI), `[tool.uv]`.
- CI: `uv sync` antes de tudo.
- Dev local: `uv sync && uv run casa --help`.

## ADR-015 — CLI com Typer

**Data**: 2026-05-28
**Decisão**: CLI implementada com **Typer**. Comandos planeados: `run`, `backfill`, `validate-config`, `list-regions`.
**Motivo**: type-hint-driven, auto-completion, help legível. Para 4+ sub-commands a verbosidade do argparse stdlib começa a doer.
**Implicações**:
- 1 dependência: `typer[all]` (~2 MB).
- `casa run --region oeiras --month 2026-04` é o entrypoint principal; reutilizado pelo workflow GHA com `casa run --region $REGION --month $MONTH`.
- Mantém um `__main__.py` para `python -m casa ...` funcionar.

## ADR-016 — Sequencial entre regiões na v1

**Data**: 2026-05-28
**Decisão**: o workflow GHA mensal processa regiões **sequencialmente** num único job. Estimativa total: 15–24 min para 3 regiões.
**Alternativa rejeitada na v1**: `strategy.matrix` paralela. Vantagem: ~5–8 min total. Desvantagem: cada região termina em momentos diferentes — o último a terminar é que faz upload do manifesto `releases.json` e push à branch `data`, exigindo lock/sync. Adiciona complexidade não-trivial.
**Motivo**: 15–24 min mensais é confortável. GHA free tier dá 2000 min/mês private (~80 execuções inteiras). Simplicidade > optimização prematura.
**Re-avaliar quando**: número de regiões > 5, ou se o tempo por região aumentar (mais bandas, mais resolução).

## ADR-017 — Orquestração sequencial e inputs pré-alinhados (Bloco 3)

**Data**: 2026-05-29
**Decisão**:
1. O loop de janelas do `pipeline.py` é **sequencial** na v1. `asyncio` não se aplica (trabalho CPU/GDAL-bound, não I/O-await); o paralelismo real (`concurrent.futures.ProcessPoolExecutor` sobre janelas) fica adiado conforme ADR-012, com a costura de acumulação desenhada para o permitir sem reescrita.
2. O `pipeline.py` assume os rasters de entrada **já na grade-alvo comum** (mesmo CRS/transform/shape). O resampling (Sentinel-3 LST 1 km→10 m via `WarpedVRT`) e a exportação GEE vivem na camada `inputs/` (offline, bloco posterior). O pipeline lê a grade do raster de referência (banda red) e valida que os restantes batem por shape.
**Motivo**: mantém o Bloco 3 focado em windowing + matemática + acumulação, testável com fixtures GeoTIFF sintéticas sem depender dos dados reais Sentinel (ainda por migrar) nem de acesso GEE (ainda por aprovar).
**Implicações**:
- `grid.py` calcula a grade-alvo (bbox→UTM→10 m) que a camada de prep usará para reprojectar/resamplar; o `pipeline.py` confia nela.
- Masking geométrico fino (rasterizar WKT) e WarpedVRT ficam como TODO da camada `inputs/`.

## ADR-010 — Janela temporal mensal

**Data**: 2026-05-27
**Decisão**: granularidade = **mês**. Cron mensal, COG por mês por região.
**Motivo**: alinhado com o relatório original (eq. 1: NPP(x, t) com `t` em meses), captura sazonalidade, reduz processamento.
**Implicações**: histórico cresce 12 ficheiros/região/ano. Para Oeiras+Lisboa+Flores ao longo de 5 anos = 180 COGs.
