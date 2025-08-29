# EDWH Odoo Plugin

[![PyPI - Version](https://img.shields.io/pypi/v/edwh-odoo-plugin.svg)](https://pypi.org/project/edwh-odoo-plugin)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/edwh-odoo-plugin.svg)](https://pypi.org/project/edwh-odoo-plugin)

An EDWH plugin for Odoo XMLRPC operations, providing advanced search functionality for projects, tasks, logs, and files.

## Installation

This plugin is designed to work with the [EDWH](https://github.com/educationwarehouse/edwh) task runner system.

### Install EDWH

First, install EDWH using pipx (recommended):

```bash
pipx install edwh
```

For more information about EDWH installation and usage, see the [EDWH README](https://github.com/educationwarehouse/edwh).

### Install this Plugin

```bash
# Install from PyPI (when published)
pipx inject edwh edwh-odoo-plugin

# Or install from source
pipx inject edwh .

# Or install with EDWH plugin manager
edwh plugin.add edwh-odoo-plugin
```

### Verify Installation

```bash
edwh --help
# You should see 'odoo' in the available namespaces

edwh odoo --help
# Shows available odoo commands
```

## Plugin Information

- **pip name**: `edwh-odoo-plugin`
- **plugin name**: `edwh[odoo]` (when available)
- **subcommand namespace**: `odoo`

## Tools

### `text_search.py` - Unified Search Tool
Geavanceerde zoekfunctionaliteit voor Odoo projecten, taken, logs EN bestanden.

**Zoekt door:**
- Project namen en beschrijvingen
- Taak namen en beschrijvingen  
- Project en taak log berichten (mail.message)
- **NIEUW**: Bestandsnamen en metadata
- Met tijd-gebaseerde filtering om server overbelasting te voorkomen

**Gebruik:**
```bash
# Tekst zoeken (zoals voorheen)
python text_search.py "zoekterm" --since "1 week"
python text_search.py "bug fix" --since "2 dagen" --type tasks

# Bestanden zoeken (NIEUW!)
python text_search.py "report" --include-files --file-types pdf docx
python text_search.py "screenshot" --files-only --file-types png jpg
python text_search.py "document" --include-files --stats

# Bestanden downloaden (NIEUW!)
python text_search.py --download 12345 --download-path ./my_files/

# Gecombineerd zoeken
python text_search.py "client meeting" --include-files --since "1 maand"
```

**Opties:**
- `--since`: Tijd referentie in Engels of Nederlands (bijv. "1 week", "3 days"/"3 dagen", "2 months"/"2 maanden")
- `--type`: Wat te doorzoeken (all, projects, tasks, logs, **files**)
- `--include-files`: **NIEUW**: Zoek ook in bestandsnamen
- `--files-only`: **NIEUW**: Zoek alleen in bestanden
- `--file-types`: **NIEUW**: Filter op bestandstypes (pdf, docx, png, etc.)
- `--download`: **NIEUW**: Download bestand op ID
- `--download-path`: **NIEUW**: Download directory
- `--stats`: **NIEUW**: Toon bestandsstatistieken
- `--no-logs`: Sluit log berichten uit
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

