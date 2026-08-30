# Dataset TACO

`taco.json` contém alimentos da **Tabela Brasileira de Composição de Alimentos
(TACO), 4ª edição**, publicada pelo NEPA/UNICAMP. A fonte oficial é
<https://nepa.unicamp.br/publicacoes/tabela-taco-excel/>; os dados foram obtidos em
2026-08-29.

O uso e a redistribuição deste dataset devem atribuir e citar o NEPA/UNICAMP. Seis
alimentos da planilha foram omitidos porque a fonte não quantifica suas calorias:
iogurte sabor abacaxi, leite de vaca desnatado UHT, leite de vaca integral, sal dietético,
sal grosso e coco verde cru. Quando as calorias eram conhecidas, macros não quantificados
foram representados como `0`; fibra continua `null` quando não quantificada.

A atribuição exibida junto aos alimentos é: `Tabela Brasileira de Composição de Alimentos
(TACO), 4ª edição. NEPA/UNICAMP.`

Para reconstruir o arquivo a partir da planilha oficial, use:

```bash
uv run --with openpyxl python scripts/build_taco_dataset.py
```

Para importar ou atualizar os alimentos globais no banco:

```bash
uv run python scripts/import_taco.py
```
