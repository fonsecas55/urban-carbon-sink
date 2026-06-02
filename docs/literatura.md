# Literatura — Notas por Referência

Bibliografia operacional. Cada entrada: o que o paper contribui, o que **não** contribui, e como é usado na refatoração.

## Core CASA — Light Use Efficiency

### Potter et al. 1993 — *Terrestrial ecosystem production: a process model based on global satellite and surface data*

- Modelo CASA original. ε_max **uniforme** = 0.389 g C/MJ.
- Define `T_opt` como climatológico (não a média da cena), formulação de `T_ε1`, `T_ε2`.
- Limitação reconhecida: ε_max uniforme é inadequado para mistura de biomas em escalas regionais.
- **Uso na refatoração**: base teórica; usado para sanity-check (ordem de magnitude do εmax) e formulação T_ε1/T_ε2.

### Wu, Chen, E, et al. 2022 — *Improved CASA model based on satellite remote sensing data: simulating NPP of Qinghai Lake basin alpine grassland*, GMD 15:6919

- Doi: `10.5194/gmd-15-6919-2022`
- Versão "improved" do CASA que o relatório do utilizador adopta como referência principal.
- Introduz **WSC com SIMI** (eq. 3-5): `WSC = 0.5 + 0.5·(1 − NSIMI)`, `SIMI = 0.7071·√(SWIR1² + SWIR2²)`.
- Usa `SIMI_min/max` por imagem (validado contra um único mês em Qinghai).
- **Não tabula ε_max**, **não dá fórmula FPAR explícita**, **não dá `T_ε1/T_ε2` explícitos**. Estas três peças aparecem no relatório do utilizador mas vêm de outras fontes.
- **Uso na refatoração**: fórmula WSC; constantes SWIR.

### Xu, Wang, Li 2023 — *NPP and Vegetation Carbon Sink Capacity Estimation of Urban Green Space Using the Optimized CASA Model: A Case Study of Five Chinese Cities*, Atmosphere 14:1161

- Doi: `10.3390/atmos14071161`
- **Paper-chave** para a refatoração. Implementa CASA com Sentinel-2 L2A em 5 cidades chinesas (Beijing, Guangzhou, Shanghai, Shenyang, Xi'an).
- Fornece:
  - Fórmula FPAR via NDVI e SR (eq. 3-6) com `FPAR_min=0.001`, `FPAR_max=0.95`, `NDVI_min/max` como percentis **5%/95% por tipo de vegetação**.
  - **Tabela 1: ε_max via MOD17 BPLUT** — Deciduous Needleleaf=1.086, Evergreen Needleleaf=0.962, Deciduous Broadleaf=1.165, Evergreen Broadleaf=1.268, Mixed Forest=1.051, Shrubland=1.061, Grassland=0.86, Cropland=1.044, Wetland=0.86 g C/MJ.
  - Validação contra MOD17A3H — R² > 0.5 para todas as classes UGS.
- **Uso na refatoração**: fonte default para fórmula FPAR e tabela ε_max.

### Dong et al. 2025 — *Assessing Spatiotemporal Dynamics of NPP in Shandong Province Using the CASA Model and Google Earth Engine*, Remote Sens. 17:488

- Doi: `10.3390/rs17030488`
- **Pipeline análogo ao escolhido pelo utilizador**: CASA + Google Earth Engine, série temporal longa (2001–2020).
- Análise por trend, Moran's I, PLS-SEM.
- **Uso na refatoração**: referência técnica para o desenho do pipeline GHA Cron + GEE (Fase 4).

## Citação errada no relatório original

### Papale et al. 2011 (referência [41] do relatório do utilizador)

- O relatório cita "D. Papale, M. Reichstein, D. Aubinet, et al., *Towards a standardized processing of Net Ecosystem Exchange measured with eddy covariance technique*, Biogeosciences 8:999" como fonte da tabela ε_max para Mediterrâneo.
- **Verificação (2026-05-27)**: o DOI `10.5194/bg-8-999-2011` aponta na realidade para **Horn & Schulz 2011**, *Identification of a general light use efficiency model for gross primary production*. Paper diferente.
- Nem Horn & Schulz, nem o Papale et al. real, tabulam `ε_max` por bioma para Mediterrâneo.
- Conclusão: a **origem dos valores `Tree=1.0, Shrub=0.7, Grass=1.04, Crop=0.9, Bare=0.25` no relatório é desconhecida**.

## Não-CASA (lidos mas descartados)

### bg-22-725-2025 (Lindén et al. 2025) — *Modelling carbon balance of an urban site in Helsinki*

- Compara modelos process-based (JSBACH, LPJ-GUESS, SUEWS) em Helsinki.
- Não é LUE/CASA, não tem ε_max tabulado. **Não relevante** para a refatoração.

### *The Utility of Sentinel-2 Spectral Data in Quantifying...*

- Estimativa de LAI/biomassa florestal via Sentinel-2. Não cobre LUE/CASA. **Não relevante**.

## Dados de entrada — fontes externas

- **Sentinel-2 L2A** (B4, B8, B11, B12) — Copernicus Data Space Ecosystem. Acesso via Sentinel Hub API ou directo via OData/openEO.
- **Sentinel-3 SLSTR LST** (Land Surface Temperature, dia/noite) — Copernicus. Resolução 1 km.
- **Global Solar Atlas GHI** — `GHI.tif`, média 1994–2018, kWh/m²/dia, 9 arc-sec (~250 m). Base climatológica do SOL.
- **CAMS Solar Radiation Time-series** — ECMWF. Variação mensal de GHI por coordenada. Acesso via Atmosphere Data Store.
- **Google Earth Engine — `GOOGLE/DYNAMICWORLD/V1`** — máscara de cobertura do solo near-real-time, 9 classes, 10 m de resolução, actualização ~5 dias. Substitui ESA WorldCover estático.
- **INE / Eurostat** — população por concelho e emissões per capita.

## Calibração e validação

- **Validação contra Qinghai (Wu 2022)**: o relatório do utilizador conseguiu reproduzir o histograma de NPP (0.33–166.2 g C/m²/mês vs original 0.11–149.4). Métricas-alvo: RMSE ≤ 26.36, MAPE ≤ 22.14%.
- **Validação contra MOD17A3H (Xu 2023)**: R² > 0.5 para todas as classes de área verde urbana, em todas as 5 cidades.
- **A nossa validação**: a definir. Provavelmente comparação com MOD17A3H para Oeiras/Lisboa + valores absolutos do relatório (com nota da divergência por causa da mudança ε_max).
