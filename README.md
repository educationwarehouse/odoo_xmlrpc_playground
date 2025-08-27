# Odoo XMLRPC Playground

Dit is een experimenteer plek om toegang via XMLRPC te krijgen tot odoo en daar ook echt iets mee te kunnen.

## Tools

### `text_search.py` - Advanced Text Search
Geavanceerde tekst zoekfunctionaliteit voor Odoo projecten en taken.

**Zoekt door:**
- Project namen en beschrijvingen
- Taak namen en beschrijvingen  
- Project en taak log berichten (mail.message)
- Met tijd-gebaseerde filtering om server overbelasting te voorkomen

**Gebruik:**
```bash
python text_search.py "zoekterm" --since "1 week"
python text_search.py "bug fix" --since "2 dagen" --type tasks
python text_search.py "client meeting" --since "1 maand" --include-logs
python text_search.py "urgent" --type tasks --no-descriptions
```

**Opties:**
- `--since`: Tijd referentie (bijv. "1 week", "3 dagen", "2 maanden")
- `--type`: Wat te doorzoeken (all, projects, tasks, logs)
- `--exclude-logs`: Sluit log berichten uit
- `--no-descriptions`: Zoek alleen in namen, niet in beschrijvingen
- `--limit`: Beperk aantal resultaten
- `--export`: Exporteer naar CSV bestand
- `--verbose`: Toon gedetailleerde zoek informatie

### `search.py` - File Search
Zoekt naar bestanden in projecten en onder taken, omdat die niet altijd gevonden kunnen worden via de standaard interface.

**Functionaliteit:**
- Zoek alle bestanden gekoppeld aan projecten en taken
- Filter op bestandstype (MIME type)
- Zoek in specifieke projecten
- Download bestanden
- Export naar CSV
- Uitgebreide statistieken

**Gebruik:**
```python
from search import OdooProjectFileSearchFinal

zoeker = OdooProjectFileSearchFinal()
bestanden = zoeker.zoek_alle_project_bestanden()
zoeker.print_resultaten(bestanden)
```

## Setup

1. Installeer dependencies:
```bash
pip install openerp_proxy python-dotenv
```

2. Maak `.env` bestand aan:
```
ODOO_HOST=education-warehouse.odoo.com
ODOO_DATABASE=education-warehouse
ODOO_USER=username@domain.com
ODOO_PASSWORD=jouw_api_key
```

3. Run de tools:
```bash
python text_search.py "zoekterm"
python search.py
```

## Modules

- `odoo_base.py`: Gedeelde functionaliteit voor Odoo connecties
- `text_search.py`: Tekst zoeken in projecten, taken en logs
- `search.py`: Bestand zoeken en download functionaliteit

