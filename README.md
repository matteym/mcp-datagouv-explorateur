# datagouv-enhanced

`datagouv-enhanced` est un **wrapper** du MCP data.gouv deja existant:  
`https://mcp.data.gouv.fr/mcp`

Le MCP de base fait la recherche.  
Ce projet ajoute une couche pratique pour le scoring et le ranking.

## Deux approches differentes

### 1) Approche Agent (editeur de code / IA) - recommande

- Tu demandes directement a l'IA.
- Tu n'as pas besoin de modifier les envs a chaque requete.
- L'IA appelle les outils MCP pour toi.

Exemple de demande:
`cherche les datasets pertinents pour le prix de l'immobilier en gironde `

### 2) Approche API (tools MCP en direct)

- Tu appelles toi-meme les tools.
- Tu dois modifier uniquement les entrees ci-dessous (pas de duplication).

Source de verite (une seule par entree) :

- `mcp-datagouv-enhanced/.env`
  - `SEARCH_TERMS` : terme de recherche principal
  - `USE_CASE` : objectif metier
  - `MCP_URL` : endpoint du MCP data.gouv
- `datagouv_analyze(user_request="...")`
  - `user_request` : contrainte runtime (ex: "priorite idf", "bretagne ou idf")

Regle : ne repete pas `SEARCH_TERMS` dans le code ni dans un autre parametre.

## Outils MCP exposes

- `datagouv_setup`
- `datagouv_fetch`
- `datagouv_fetch_datasets`
- `datagouv_fetch_api`
- `datagouv_analyze(user_request="")`

## Fichiers de sortie (outputs MCP)

Tous les chemins sont sous `mcp-datagouv-enhanced/`.

### `datagouv_fetch` (ou `datagouv_fetch_datasets` / `datagouv_fetch_api`)

- `dataset/result_{terme}_{kind}.txt` — collecte datasets (`kind` : `geospatial`, `json`, `other`)
- `api/result_{terme}_{kind}.txt` — collecte APIs (même nommage)

`{terme}` = slug de `SEARCH_TERMS` (espaces → `_`). Les pages s’accumulent dans le même fichier.

### `datagouv_analyze`

- `dataset/relevance_scores.json` — pertinence par dataset
- `api/relevance_scores.json` — pertinence par API
- `dataset/ranking_report.md` — top 10 datasets
- `api/ranking_report.md` — top 10 APIs
- `ranking_report.md` — rapport combiné (racine du package)
- `ranking_report.json` — classement JSON (racine du package)


