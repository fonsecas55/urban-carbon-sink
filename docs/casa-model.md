# Modelo CASA — Derivação Matemática

Documento operacional para o engenheiro que implementa o pipeline. Não substitui a literatura — ver `literatura.md` para fontes.

## 1. Equação principal

$$
NPP(x, t) = 0.5 \cdot SOL(x, t) \cdot FPAR(x, t) \cdot \varepsilon_{max} \cdot T_{\varepsilon 1} \cdot T_{\varepsilon 2}(x, t) \cdot WSC(x, t)
$$

| Termo | Significado | Unidade |
|---|---|---|
| `NPP(x, t)` | Net Primary Productivity por célula `x` no mês `t` | g C / m² / mês |
| `0.5` | Fracção PAR da radiação solar total (0.4–0.7 µm) | adim. |
| `SOL(x, t)` | Radiação solar total incidente | MJ / m² / mês |
| `FPAR(x, t)` | Fracção da PAR absorvida pela vegetação | adim. [0, 1] |
| `ε_max` | Eficiência máxima de conversão luz→biomassa, dependente do tipo de vegetação | g C / MJ |
| `T_ε1` | Stress por baixas temperaturas | adim. [0, 1] (constante por cena) |
| `T_ε2(x, t)` | Stress por altas temperaturas | adim. [0, 1] (por pixel) |
| `WSC(x, t)` | Water Stress Coefficient | adim. [0.5, 1] |

Conversão final: `NPP(CO₂) = (44/12) · NPP(C) ≈ 3.67 · NPP(C)`.

## 2. FPAR

Implementação escolhida (Xu et al. 2023, eq. 3–6) — adoptada na refatoração para **garantir coerência temporal**:

```
FPAR(x, t) = 0.5 · (FPAR_NDVI + FPAR_SR)

FPAR_NDVI = (NDVI − NDVI_min_i) / (NDVI_max_i − NDVI_min_i) · (FPAR_max − FPAR_min) + FPAR_min
FPAR_SR   = (SR   − SR_min_i)   / (SR_max_i   − SR_min_i)   · (FPAR_max − FPAR_min) + FPAR_min

SR = (1 + NDVI) / (1 − NDVI)
```

Com:
- `FPAR_max = 0.95`, `FPAR_min = 0.001` (independentes do tipo).
- `NDVI_min_i`, `NDVI_max_i` = percentis 5% / 95% de NDVI **por tipo de vegetação `i`** (Dynamic World), calibrados sobre amostra histórica grande. **Não calcular por imagem.**
- `NDVI = (B8 − B4) / (B8 + B4)`, vectorizado com NumPy (sem loops).

**Divergência face ao relatório original**: o relatório usa min/max globais por imagem (eq. 2, p.15), que introduz drift temporal — inaceitável para uma aplicação web que serve qualquer mês via API.

## 3. WSC

Wu et al. 2022 (GMD), eq. 3–5:

```
SIMI = 0.7071 · sqrt(SWIR1² + SWIR2²)        (B11 ≈ 1610 nm, B12 ≈ 2190 nm)
NSIMI = (SIMI − SIMI_min) / (SIMI_max − SIMI_min)
WSC = 0.5 + 0.5 · (1 − NSIMI)
```

`SIMI_min`, `SIMI_max` = percentis 2% / 98% sobre amostra histórica grande (não por imagem). Mesmo motivo do FPAR.

Reflectâncias B11, B12 normalizadas para `[0, 1]` antes do cálculo (factor de escala Sentinel-2 = 10000).

## 4. Stress térmico `T_ε1`, `T_ε2`

Potter 1993, ajustado por Wu 2022. `T_day`, `T_night` provêm de Sentinel-3 LST.

```
T_mean(x, t) = 0.5 · (T_day + T_night)        (em °C)
T_opt = climatológico por bioma (NÃO a média da cena)

T_ε1 = 0.8 + 0.02 · T_opt − 0.0005 · T_opt²    (constante por cena)
T_ε2(x, t) = 1.184 / { [1 + exp(0.2·(T_opt − 10 − T_mean))] · [1 + exp(0.3·(−T_opt − 10 + T_mean))] }
```

**Correcção crítica face ao código actual**: o código `T1_T2_CALC.py:67-71` calcula `T_opt = nanmean(T_mean)` da imagem, que é cientificamente errado. `T_opt` é uma constante climatológica por bioma (Potter 1993). Implementação correcta: tabela `T_opt` por classe Dynamic World, calibrada a partir de séries longas de NPP histórico ou tabulada por literatura.

## 5. SOL

Construção do mapa SOL mensal por região:

```
SOL_base = GHI(Global Solar Atlas, kWh/m²/dia)
SOL(x, t) = SOL_base · 3.6 · (1 + VAR_PCT_MES[t] / 100) · n_dias(t)
```

Onde `VAR_PCT_MES[t]` é a variação percentual mensal vs. média anual, obtida de CAMS para um ponto-referência da região (limitação: aplicada uniformemente).

Para uma aplicação web dinâmica: alternativa preferida é chamar CAMS time-series directamente para o mês pedido, não usar tabela hardcoded. Decisão técnica adiada para Fase 4.

## 6. ε_max — tabela operacional

Pipeline mapeia **schema canónico de landcover → ε_max** (ver [ADR-011](decisoes-arquitetura.md#adr-011--schema-canónico-de-cobertura-do-solo)). Default (Xu 2023 / MOD17 BPLUT):

| Canonical | Código | ε_max (g C/MJ) | Origem | DW source | ESA source |
|---|---|---|---|---|---|
| `non_vegetation` | 0 | 0 | máscara | `built`, `water`, `bare`, `snow_and_ice` | 50, 60, 70, 80, 100 |
| `trees` | 1 | 1.106 | média BPLUT forest | `trees` | 10 |
| `shrub_and_scrub` | 2 | 1.061 | BPLUT Shrubland | `shrub_and_scrub` | 20 |
| `grass` | 3 | 0.86 | BPLUT Grassland | `grass` | 30 |
| `crops` | 4 | 1.044 | BPLUT Cropland | `crops` | 40 |
| `flooded_vegetation` | 5 | 0.86 | BPLUT Wetland | `flooded_vegetation` | 90, 95 |

Override "relatório" disponível em `config/epsilon_max/relatorio.yml` para reproduzir resultados publicados (origem incerta) — `trees=1.0`, `shrub_and_scrub=0.7`, `grass=1.04`, `crops=0.9`, `non_vegetation=0` (ou `0.25` se mapeares ESA-60/`bare` para classe canónica `bare` em vez de `non_vegetation`).

Os adaptadores `dw_to_canonical()` e `esa_to_canonical()` em `casa/landcover.py` garantem que o módulo `emax` nunca vê DW ou ESA directos — só os códigos canónicos. Trocar a fonte (DW ↔ ESA fallback) não afecta o `emax` nem precisa de mexer na tabela `config/`.

## 7. Pós-processamento

1. **Conversão para CO₂**: `NPP_CO2 = NPP_C · 44/12 ≈ NPP_C · 3.67`.
2. **Soma espacial → toneladas**: `total_t_C = sum(NPP_C[válidos]) · area_pixel_m² / 1e6`.
   - Sentinel-2 nativo: 10×10 m → `area_pixel = 100 m²`. **O código actual (`NPP_RESULT.py:54`) divide só por 1e6 sem multiplicar pela área — possível bug de unidades, a confirmar reproduzindo com raster real e área Oeiras**.
3. **Máscara espacial**: aplicar geometria WKT/shapefile da região (não usar o "hack do último pixel").
