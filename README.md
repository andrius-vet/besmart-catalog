# BeSmart Catalog (GitHub + Netlify + Decap CMS)

Šiame repozitoriume laikomas turinio katalogas:
- `catalog/` JSON failai (videos, categories, category_items) su **items/mapping** struktūra
- `admin/` yra Decap CMS UI (`/admin/` maršrutas serveryje)
- `static/uploads/` – vieta paveikslėliams (jei reikės)
- `netlify.toml`, `_headers` – CORS/Cache valdymui

## Struktūra

- `catalog/index.json` – manifestas (nurodo failų pavadinimus)
- `catalog/videos.json` – **{ "items": [...] }**
- `catalog/categories.json` – **{ "items": [...] }**
- `catalog/category_items.json` – **{ "mapping": [ { categoryId, itemIds: [...] }, ... ] }**

> Pastaba: JSON failai naudoja objektą su `items`/`mapping`, kad būtų patogiau redaguoti per Decap CMS.
> App'e skaitykite atitinkamus laukus (`items`, `mapping`).

## Greitas paleidimas lokaliai
- Įdiekite `npx decap-server` (arba naudokite Netlify CLI) jei norite lokalaus CMS testavimo.
- Atidarykite `admin/index.html` per lokalaus serverio adresą (pvz., Netlify dev).
