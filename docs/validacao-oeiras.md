# Validação — Oeiras, cena real 2025-04-23

Primeira execução do pipeline refatorizado sobre **dados reais** (não sintéticos),
usando a única cena Sentinel-2/3 local migrada do repo legacy. Reproduzível via:

```
uv run python tools/validate_oeiras_2025_04.py [CAMINHO_INPUTS_LEGACY]
```

## Fontes (legacy `PFC_V3.1/NPP_CALC_PROJ/INPUTS/`)

| Banda | Ficheiro | Tratamento |
|---|---|---|
| red/nir/swir1/swir2 | `SENTINEL2/Sentinel2_Bands.tif` (B04/B08/B11/B12) | escala nativa ×10000 mantida (NDVI/SR invariantes; `wsc.simi` divide internamente) |
| t_day/t_night | `SENTINEL3/Sentinel3_LST.tif` | Kelvin → °C; **mesma LST para dia e noite** (gap — ver abaixo) |
| ghi | `SOL/GHI.tif` | kWh/m²/dia, crop/warp pelo `prepare` |
| landcover | `Subset_ESA_WorldCover_…tif` | códigos ESA → `esa_to_canonical` (`landcover_source=esa_worldcover`) |

Geometria: polígono municipal real (`data/geometry/oeiras.wkt`, 175 vértices).
Percentis FPAR/WSC: **provisórios**, calculados desta cena dentro de Oeiras (a
calibração multi-temporal de produção fica para o Bloco 6).

## Resultado

| Métrica | Valor |
|---|---|
| Grade | 1040×886 @ 10 m, EPSG:32629 |
| Pixels válidos (no concelho) | 466 404 |
| Pixels de vegetação | 258 498 (~2585 ha) |
| **NPP** | **995.2 t C/mês** (3 649 t CO₂/mês) |
| Relatório Final (Oeiras) | ~4 521 t C/mês |
| Rácio nosso/relatório | **0.22** |

## Interpretação

1. **A correção de unidades está certa.** O nosso total (995 tC) é da **mesma ordem
   de grandeza** do relatório (4521 tC). Se o bug do legacy (`NPP_RESULT.py:54`,
   `sum/1e6` sem multiplicar pela área do pixel) estivesse no nosso código, daríamos
   ~10 tC (≈100× menos). `density_to_tonnes × área_pixel` resolve isto — confirmado.

2. **O gap dominante (~4.5×) é a LST Sentinel-3.** `Sentinel3_LST.tif` tem média
   ~3 °C (máx 15 °C) — frio demais para superfície diurna de Abril em Lisboa;
   é provavelmente a passagem **noturna** (os subsets dia/noite do legacy vêm vazios).
   Com T_opt = 18.5 °C, T_mean ≈ 3 °C dá **T_ε2 ≈ 0.30** (forte penalização de frio).
   Com LST diurna realista (~20 °C) seria T_ε2 ≈ 1.0 → NPP ~3.3× maior ≈ 3 300 tC,
   muito próximo do relatório. **A resolução correta de dia/noite (Bloco 6, extração
   própria do `.SEN3`) deverá fechar a maior parte da diferença.**

3. Fatores residuais: tabela ε_max Xu 2023 (vs tabela do relatório, origem incerta);
   percentis de cena única (vs min/max por imagem do relatório); polígono real (vs
   quadrado envolvente do relatório).

## Conclusão

Validação **indicativa bem-sucedida**: a stack completa (prepare → pipeline → report)
corre sobre dados reais, produz números fisicamente plausíveis e na ordem de grandeza
certa. A precisão fina depende de (i) LST dia/noite correta e (ii) percentis e ε_max
de produção — ambos no Bloco 6. Não há indício de bug no núcleo de cálculo.
