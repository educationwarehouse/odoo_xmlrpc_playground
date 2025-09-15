#!/usr/bin/env python3
"""
Odoo Project Bestand Zoeker - DEFINITIEVE WERKENDE VERSIE
=========================================================

Gebaseerd op testresultaten:
✅ 'IN' operator werkt perfect
✅ Platte domein structuur is correct
✅ Het probleem zat in geneste lijst structuren

Deze versie gebruikt:
- 'IN' operator (werkt prima in jouw Odoo)
- Platte domein structuur
- Alle project/task bestanden zoeken
- Werkende client configuratie

Installatie:
    pip install openerp_proxy python-dotenv

.env bestand:
    ODOO_HOST=education-warehouse.odoo.com
    ODOO_DATABASE=education-warehouse
    ODOO_USER=username
    ODOO_PASSWORD=jouw_api_key

Auteur: Perplexity & Remco
Datum: Augustus 2025
"""

import os
import base64
import csv
import time
from functools import wraps
from datetime import datetime, timedelta
from .odoo_base import OdooBase
import warnings

# Suppress the pkg_resources deprecation warning from odoo_rpc_client globally
warnings.filterwarnings("ignore", 
                      message="pkg_resources is deprecated as an API.*",
                      category=UserWarning)

def timing_decorator(operation_name):
    """Decorator to time operations and log them"""
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            if hasattr(self, 'verbose') and self.verbose:
                start_time = time.time()
                print(f"⏱️  Starting {operation_name}...")
            
            result = func(self, *args, **kwargs)
            
            if hasattr(self, 'verbose') and self.verbose:
                elapsed = time.time() - start_time
                print(f"✅ {operation_name} completed in {elapsed:.2f}s")
            
            return result
        return wrapper
    return decorator

def log_timing(self, operation, start_time, extra_info=""):
    """Helper method to log timing information"""
    if self.verbose:
        elapsed = time.time() - start_time
        print(f"⏱️  {operation}: {elapsed:.2f}s {extra_info}")


class OdooProjectFileSearchFinal(OdooBase):
    """
    Definitieve werkende versie van de project bestand zoeker

    Gebaseerd op succesvolle tests:
    - Gebruikt 'IN' operator (werkt in jouw setup)
    - Platte domein structuur
    - Geen geneste lijst problemen
    """

    def __init__(self, verbose=False):
        """
        Initialiseer met .env configuratie
        """
        super().__init__(verbose=verbose)

    def _build_working_domain(self, project_ids=None, task_ids=None):
        """
        Bouw werkend plat domein met 'IN' operator - with size limits
        """
        conditions = []
        
        # Limit ID list sizes to prevent server overload
        max_ids = 500  # Reasonable limit for IN queries
        
        if project_ids:
            # Limit project IDs to prevent server errors
            limited_project_ids = project_ids[:max_ids] if len(project_ids) > max_ids else project_ids
            if self.verbose and len(project_ids) > max_ids:
                print(f"⚠️ Limited project IDs from {len(project_ids)} to {max_ids}")
            
            project_condition = ['&', ('res_model', '=', 'project.project'), ('res_id', 'in', limited_project_ids)]
            conditions.append(project_condition)

        if task_ids:
            # Limit task IDs to prevent server errors
            limited_task_ids = task_ids[:max_ids] if len(task_ids) > max_ids else task_ids
            if self.verbose and len(task_ids) > max_ids:
                print(f"⚠️ Limited task IDs from {len(task_ids)} to {max_ids}")
            
            task_condition = ['&', ('res_model', '=', 'project.task'), ('res_id', 'in', limited_task_ids)]
            conditions.append(task_condition)

        # Combineer met OR - PLATTE STRUCTUUR
        if len(conditions) == 1:
            return conditions[0]
        elif len(conditions) == 2:
            # Platte OR structuur: ['|', condition1, condition2]
            return ['|'] + conditions[0] + conditions[1]
        else:
            return []

    def _add_filters(self, base_domain, zoek_term=None, bestandstype=None, date_from=None):
        """
        Voeg filters toe aan werkend basis domein
        """
        if not base_domain:
            return []

        domain = base_domain[:]

        # Voeg filters toe met AND - platte structuur
        if zoek_term:
            domain = ['&'] + domain + [('name', 'ilike', zoek_term)]

        if bestandstype:
            domain = ['&'] + domain + [('mimetype', 'ilike', bestandstype)]

        if date_from:
            date_str = date_from.strftime('%Y-%m-%d %H:%M:%S')
            domain = ['&'] + domain + [('create_date', '>=', date_str)]

        return domain

    @timing_decorator("All Project Files Search")
    def zoek_alle_project_bestanden(self, zoek_term=None, bestandstype=None):
        """
        Zoek alle bestanden in projecten en taken - werkende versie
        """
        start_time = time.time()
        print("🔍 Zoeken naar alle project bestanden...")

        try:
            # Haal ALLE project en task IDs op
            query_start = time.time()
            alle_projecten = self.projects.search_records([])
            alle_taken = self.tasks.search_records([])
            log_timing(self, "Project/Task ID query", query_start, f"({len(alle_projecten)} projects, {len(alle_taken)} tasks)")

            project_ids = [p.id for p in alle_projecten]
            task_ids = [t.id for t in alle_taken]

            print(f"📊 Data overzicht:")
            print(f"   Projecten: {len(project_ids)}")
            print(f"   Taken: {len(task_ids)}")

            # Bouw werkend domein
            domain_start = time.time()
            base_domain = self._build_working_domain(project_ids, task_ids)
            final_domain = self._add_filters(base_domain, zoek_term, bestandstype)
            log_timing(self, "Domain building", domain_start)

            print(f"🔧 Domein: {final_domain}")

            # Zoek bestanden
            search_start = time.time()
            bestanden = self.attachments.search_records(final_domain)
            log_timing(self, "File search", search_start, f"({len(bestanden)} files)")

            print(f"📄 {len(bestanden)} bestanden gevonden")

            # Verrijk bestanden
            enrich_start = time.time()
            result = self._verrijk_bestanden(bestanden)
            log_timing(self, "File enrichment", enrich_start, f"({len(result)} files)")
            log_timing(self, "Total file search", start_time)

            return result

        except Exception as e:
            print(f"❌ Fout bij zoeken: {e}")
            import traceback
            print(f"   Traceback: {traceback.format_exc()}")
            return []

    @timing_decorator("Project-Only Files Search")
    def zoek_alleen_project_bestanden(self, zoek_term=None, bestandstype=None):
        """
        Zoek alleen bestanden die direct aan projecten gekoppeld zijn
        """
        start_time = time.time()
        print("🔍 Zoeken naar project bestanden (geen taken)...")

        try:
            query_start = time.time()
            alle_projecten = self.projects.search_records([])
            log_timing(self, "Project query", query_start, f"({len(alle_projecten)} projects)")
            
            project_ids = [p.id for p in alle_projecten]

            print(f"📂 {len(project_ids)} projecten")

            # Simpel domein: alleen project bestanden
            domain_start = time.time()
            base_domain = ['&', ('res_model', '=', 'project.project'), ('res_id', 'in', project_ids)]
            final_domain = self._add_filters(base_domain, zoek_term, bestandstype)
            log_timing(self, "Domain building", domain_start)

            print(f"🔧 Domein: {final_domain}")

            search_start = time.time()
            bestanden = self.attachments.search_records(final_domain)
            log_timing(self, "File search", search_start, f"({len(bestanden)} files)")
            
            print(f"📄 {len(bestanden)} project bestanden gevonden")

            # Verrijk bestanden
            enrich_start = time.time()
            result = self._verrijk_bestanden(bestanden)
            log_timing(self, "File enrichment", enrich_start, f"({len(result)} files)")
            log_timing(self, "Total project-only search", start_time)

            return result

        except Exception as e:
            print(f"❌ Fout: {e}")
            return []

    @timing_decorator("Task-Only Files Search")
    def zoek_alleen_taak_bestanden(self, zoek_term=None, bestandstype=None):
        """
        Zoek alleen bestanden die aan taken gekoppeld zijn
        """
        start_time = time.time()
        print("🔍 Zoeken naar taak bestanden...")

        try:
            query_start = time.time()
            alle_taken = self.tasks.search_records([])
            log_timing(self, "Task query", query_start, f"({len(alle_taken)} tasks)")
            
            task_ids = [t.id for t in alle_taken]

            print(f"📋 {len(task_ids)} taken")

            # Simpel domein: alleen taak bestanden
            domain_start = time.time()
            base_domain = ['&', ('res_model', '=', 'project.task'), ('res_id', 'in', task_ids)]
            final_domain = self._add_filters(base_domain, zoek_term, bestandstype)
            log_timing(self, "Domain building", domain_start)

            print(f"🔧 Domein: {final_domain}")

            search_start = time.time()
            bestanden = self.attachments.search_records(final_domain)
            log_timing(self, "File search", search_start, f"({len(bestanden)} files)")
            
            print(f"📄 {len(bestanden)} taak bestanden gevonden")

            # Verrijk bestanden
            enrich_start = time.time()
            result = self._verrijk_bestanden(bestanden)
            log_timing(self, "File enrichment", enrich_start, f"({len(result)} files)")
            log_timing(self, "Total task-only search", start_time)

            return result

        except Exception as e:
            print(f"❌ Fout: {e}")
            return []

    @timing_decorator("Per-Project Files Search")
    def zoek_per_project(self, project_naam_of_id):
        """
        Zoek bestanden in specifiek project
        """
        start_time = time.time()
        try:
            project_start = time.time()
            if isinstance(project_naam_of_id, int):
                project = self.projects[project_naam_of_id]
            else:
                project_result = self.projects(project_naam_of_id)
                if not project_result:
                    print(f"❌ Geen project gevonden: {project_naam_of_id}")
                    return []
                project = project_result[0] if isinstance(project_result, list) else project_result
            log_timing(self, "Project lookup", project_start)

            print(f"🔍 Zoeken in project: {project.name} (ID: {project.id})")

            # Zoek taken in dit project
            task_start = time.time()
            taken = self.tasks.search_records([('project_id', '=', project.id)])
            task_ids = [t.id for t in taken] if taken else []
            log_timing(self, "Task query", task_start, f"({len(task_ids)} tasks)")

            print(f"📋 {len(task_ids)} taken in dit project")

            # Bouw domein voor dit project EN zijn taken
            domain_start = time.time()
            if task_ids:
                # Project + taken bestanden
                domain = self._build_working_domain([project.id], task_ids)
            else:
                # Alleen project bestanden
                domain = ['&', ('res_model', '=', 'project.project'), ('res_id', '=', project.id)]
            log_timing(self, "Domain building", domain_start)

            print(f"🔧 Domein: {domain}")

            search_start = time.time()
            bestanden = self.attachments.search_records(domain)
            log_timing(self, "File search", search_start, f"({len(bestanden)} files)")
            
            print(f"📄 {len(bestanden)} bestanden gevonden")

            # Verrijk bestanden
            enrich_start = time.time()
            result = self._verrijk_bestanden(bestanden)
            log_timing(self, "File enrichment", enrich_start, f"({len(result)} files)")
            log_timing(self, "Total per-project search", start_time)

            return result

        except Exception as e:
            print(f"❌ Fout bij project zoeken: {e}")
            return []

    @timing_decorator("Recent Files Search")
    def zoek_recente_bestanden(self, dagen=7):
        """
        Zoek recent toegevoegde bestanden
        """
        start_time = time.time()
        print(f"🔍 Zoeken naar bestanden van laatste {dagen} dagen")

        try:
            cutoff_date = datetime.now() - timedelta(days=dagen)

            # Alle project/task IDs
            query_start = time.time()
            project_ids = [p.id for p in self.projects.search_records([])]
            task_ids = [t.id for t in self.tasks.search_records([])]
            log_timing(self, "Project/Task ID query", query_start, f"({len(project_ids)} projects, {len(task_ids)} tasks)")

            # Bouw domein met datum filter
            domain_start = time.time()
            base_domain = self._build_working_domain(project_ids, task_ids)
            final_domain = self._add_filters(base_domain, date_from=cutoff_date)
            log_timing(self, "Domain building", domain_start)

            print(f"🔧 Domein: {final_domain}")

            search_start = time.time()
            bestanden = self.attachments.search_records(final_domain)
            log_timing(self, "File search", search_start, f"({len(bestanden)} files)")
            
            print(f"📄 {len(bestanden)} recente bestanden gevonden")

            # Verrijk bestanden
            enrich_start = time.time()
            result = self._verrijk_bestanden(bestanden)
            log_timing(self, "File enrichment", enrich_start, f"({len(result)} files)")
            log_timing(self, "Total recent files search", start_time)

            return result

        except Exception as e:
            print(f"❌ Fout: {e}")
            return []

    @timing_decorator("MIME Type Files Search")
    def zoek_per_bestandstype(self, mime_type):
        """
        Zoek bestanden op MIME type
        """
        start_time = time.time()
        print(f"🔍 Zoeken naar bestanden van type: {mime_type}")

        try:
            query_start = time.time()
            project_ids = [p.id for p in self.projects.search_records([])]
            task_ids = [t.id for t in self.tasks.search_records([])]
            log_timing(self, "Project/Task ID query", query_start, f"({len(project_ids)} projects, {len(task_ids)} tasks)")

            domain_start = time.time()
            base_domain = self._build_working_domain(project_ids, task_ids)
            final_domain = self._add_filters(base_domain, bestandstype=mime_type)
            log_timing(self, "Domain building", domain_start)

            print(f"🔧 Domein: {final_domain}")

            search_start = time.time()
            bestanden = self.attachments.search_records(final_domain)
            log_timing(self, "File search", search_start, f"({len(bestanden)} files)")
            
            print(f"📄 {len(bestanden)} bestanden van type {mime_type} gevonden")

            # Verrijk bestanden
            enrich_start = time.time()
            result = self._verrijk_bestanden(bestanden)
            log_timing(self, "File enrichment", enrich_start, f"({len(result)} files)")
            log_timing(self, "Total MIME type search", start_time)

            return result

        except Exception as e:
            print(f"❌ Fout: {e}")
            return []

    @timing_decorator("File Enrichment")
    def _verrijk_bestanden(self, bestanden):
        """
        Verrijk bestanden met project en taak informatie
        """
        start_time = time.time()
        verrijkte_bestanden = []

        for i, bestand in enumerate(bestanden):
            if self.verbose and i % 50 == 0:
                print(f"   Processing file {i+1}/{len(bestanden)}")
            
            try:
                verrijkt = {'id': bestand.id, 'naam': bestand.name, 'type_mime': bestand.mimetype or 'Onbekend', 'grootte': bestand.file_size or 0,
                    'grootte_human': self.format_file_size(bestand.file_size or 0),
                    'aangemaakt': str(bestand.create_date) if bestand.create_date else 'Onbekend',
                    'gewijzigd': str(bestand.write_date) if bestand.write_date else 'Onbekend', 'publiek': bestand.public, 'model': bestand.res_model,
                    'record_id': bestand.res_id, }

                # Voeg model-specifieke informatie toe
                if bestand.res_model == 'project.project':
                    try:
                        project = self.projects.browse(bestand.res_id)
                        verrijkt.update({'type': 'Project', 'project_naam': project.name, 'project_id': project.id,
                            'klant': project.partner_id.name if project.partner_id else 'Geen klant', })
                    except Exception as e:
                        verrijkt.update({'type': 'Project', 'project_naam': f'Project {bestand.res_id}', 'fout': f'Project info niet beschikbaar: {e}'})

                elif bestand.res_model == 'project.task':
                    try:
                        taak = self.tasks.browse(bestand.res_id)
                        verrijkt.update({'type': 'Taak', 'taak_naam': taak.name, 'taak_id': taak.id,
                            'project_naam': taak.project_id.name if taak.project_id else 'Geen project',
                            'project_id': taak.project_id.id if taak.project_id else None,
                            'toegewezen': taak.user_id.name if taak.user_id else 'Niet toegewezen', })
                    except Exception as e:
                        verrijkt.update({'type': 'Taak', 'taak_naam': f'Taak {bestand.res_id}', 'fout': f'Taak info niet beschikbaar: {e}'})

                verrijkte_bestanden.append(verrijkt)

            except Exception as e:
                print(f"⚠️  Fout bij verrijken bestand {bestand.id}: {e}")
                # Voeg minimale info toe
                verrijkte_bestanden.append({'id': bestand.id, 'naam': getattr(bestand, 'name', 'Onbekend'), 'fout': f'Verrijking gefaald: {e}'})
                continue

        log_timing(self, "File enrichment processing", start_time, f"({len(verrijkte_bestanden)} files)")
        return verrijkte_bestanden

    def download_bestand(self, attachment_id, output_path):
        """
        Download een bestand naar lokale schijf - uses shared download method
        
        Args:
            attachment_id: ID van het attachment om te downloaden
            output_path: Lokaal pad waar het bestand opgeslagen moet worden
            
        Returns:
            bool: True als succesvol, False anders
        """
        success = self.download_attachment(attachment_id, output_path)
        if success and not self.verbose:
            # Translate success message to Dutch for consistency
            print(f"✅ Gedownload naar: {output_path}")
        return success

    def export_naar_csv(self, bestanden, filename='project_bestanden.csv'):
        """
        Exporteer naar CSV
        """
        if not bestanden:
            print("❌ Geen bestanden om te exporteren")
            return

        try:
            # Convert data to strings for CSV export
            safe_bestanden = []
            for bestand in bestanden:
                safe_bestand = {}
                for k, v in bestand.items():
                    if hasattr(v, '__class__') and 'odoo' in str(v.__class__).lower():
                        # Handle Odoo objects
                        if hasattr(v, 'id'):
                            safe_bestand[k] = v.id
                        else:
                            safe_bestand[k] = str(v)
                    else:
                        safe_bestand[k] = v
                safe_bestanden.append(safe_bestand)
            
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                # Bepaal velden uit eerste bestand
                fieldnames = safe_bestanden[0].keys()
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                writer.writeheader()
                for bestand in safe_bestanden:
                    # Converteer alle waarden naar strings voor CSV
                    csv_row = {k: str(v) if v is not None else '' for k, v in bestand.items()}
                    writer.writerow(csv_row)

            print(f"✅ {len(safe_bestanden)} bestanden geëxporteerd naar {filename}")

        except Exception as e:
            print(f"❌ CSV export gefaald: {e}")

    def statistieken(self):
        """
        Toon uitgebreide statistieken
        """
        print("\n📊 PROJECT BESTAND STATISTIEKEN")
        print("=" * 60)

        try:
            # Basis aantallen
            projecten = self.projects.search_records([])
            taken = self.tasks.search_records([])

            print(f"📂 Totaal projecten: {len(projecten)}")
            print(f"📋 Totaal taken: {len(taken)}")

            # Test verschillende zoektypes
            print(f"\n📄 BESTAND AANTALLEN:")

            # Alleen project bestanden
            project_bestanden = self.zoek_alleen_project_bestanden()
            print(f"   Project bestanden: {len(project_bestanden)}")

            # Alleen taak bestanden
            taak_bestanden = self.zoek_alleen_taak_bestanden()
            print(f"   Taak bestanden: {len(taak_bestanden)}")

            # Totaal
            totaal = len(project_bestanden) + len(taak_bestanden)
            print(f"   Totaal: {totaal}")

            # Analyse van bestandstypes als er bestanden zijn
            if totaal > 0:
                alle_bestanden = project_bestanden + taak_bestanden
                self._toon_type_statistieken(alle_bestanden)

        except Exception as e:
            print(f"❌ Fout bij statistieken: {e}")

    def _toon_type_statistieken(self, bestanden):
        """
        Toon statistieken over bestandstypes
        """
        print(f"\n📊 TYPE VERDELING:")

        type_stats = {}
        grootte_totaal = 0

        for bestand in bestanden:
            mime_type = bestand.get('type_mime', 'Onbekend')
            grootte = bestand.get('grootte', 0) or 0

            grootte_totaal += grootte

            if mime_type in type_stats:
                type_stats[mime_type]['count'] += 1
                type_stats[mime_type]['size'] += grootte
            else:
                type_stats[mime_type] = {'count': 1, 'size': grootte}

        print(f"💾 Totale grootte: {self.format_file_size(grootte_totaal)}")
        print(f"\n📈 Top bestandstypes:")

        # Sorteer op aantal
        sorted_types = sorted(type_stats.items(), key=lambda x: x[1]['count'], reverse=True)

        for i, (mime_type, stats) in enumerate(sorted_types[:10], 1):
            count = stats['count']
            size = self.format_file_size(stats['size'])
            percentage = (count / len(bestanden)) * 100

            print(f"   {i:2}. {mime_type:<30} {count:4} bestanden ({percentage:5.1f}%) - {size}")

    def print_resultaten(self, bestanden, limit=20):
        """
        Print resultaten in mooie opmaak
        """
        if not bestanden:
            print("📭 Geen bestanden gevonden.")
            return

        # Convert data for safe printing
        safe_bestanden = []
        for bestand in bestanden:
            safe_bestand = {}
            for k, v in bestand.items():
                if hasattr(v, '__class__') and 'odoo' in str(v.__class__).lower():
                    # Handle Odoo objects
                    if hasattr(v, 'id'):
                        safe_bestand[k] = v.id
                    else:
                        safe_bestand[k] = str(v)
                else:
                    safe_bestand[k] = v
            safe_bestanden.append(safe_bestand)

        if limit and len(safe_bestanden) > limit:
            print(f"\n📁 Eerste {limit} van {len(safe_bestanden)} bestanden:")
            safe_bestanden = safe_bestanden[:limit]
        else:
            print(f"\n📁 {len(safe_bestanden)} bestand(en) gevonden:")

        print("=" * 90)

        for i, bestand in enumerate(safe_bestanden, 1):
            print(f"\n{i:2}. 📄 {bestand['naam']}")
            print(f"      🆔 ID: {bestand['id']}")

            if bestand.get('project_naam'):
                print(f"      📂 Project: {bestand['project_naam']}")

            if bestand.get('taak_naam'):
                print(f"      📋 Taak: {bestand['taak_naam']}")
                if bestand.get('toegewezen'):
                    print(f"      👤 Toegewezen: {bestand['toegewezen']}")

            if bestand.get('klant'):
                print(f"      🏢 Klant: {bestand['klant']}")

            print(f"      📊 Type: {bestand.get('type_mime', 'Onbekend')}")
            print(f"      📏 Grootte: {bestand.get('grootte_human', '0 B')}")
            print(f"      📅 Aangemaakt: {bestand.get('aangemaakt', 'Onbekend')}")

            if bestand.get('fout'):
                print(f"      ⚠️  Fout: {bestand['fout']}")





def main():
    """
    Hoofdfunctie met alle zoekfuncties
    """
    print("🚀 Odoo Project Bestand Zoeker - DEFINITIEVE VERSIE")
    print("=" * 70)

    try:
        # Initialiseer zoeker
        zoeker = OdooProjectFileSearchFinal()

        # Toon statistieken
        zoeker.statistieken()

        # Test verschillende zoekfuncties
        print("\n" + "=" * 70)
        print("🔍 VERSCHILLENDE ZOEKFUNCTIES TESTEN")
        print("=" * 70)

        # 1. Alle project en taak bestanden
        print("\n1️⃣ ALLE PROJECT EN TAAK BESTANDEN:")
        alle_bestanden = zoeker.zoek_alle_project_bestanden()
        zoeker.print_resultaten(alle_bestanden, limit=5)

        # 2. Alleen PDF bestanden
        print("\n2️⃣ PDF BESTANDEN:")
        pdf_bestanden = zoeker.zoek_per_bestandstype('pdf')
        zoeker.print_resultaten(pdf_bestanden, limit=3)

        # 3. Afbeeldingen
        print("\n3️⃣ AFBEELDINGEN:")
        afbeeldingen = zoeker.zoek_per_bestandstype('image')
        zoeker.print_resultaten(afbeeldingen, limit=3)

        # 4. Recente bestanden (laatste week)
        print("\n4️⃣ RECENTE BESTANDEN (laatste week):")
        recente_bestanden = zoeker.zoek_recente_bestanden(dagen=7)
        zoeker.print_resultaten(recente_bestanden, limit=5)

        # 5. Bestanden met 'test' in naam
        print("\n5️⃣ BESTANDEN MET 'TEST' IN NAAM:")
        test_bestanden = zoeker.zoek_alle_project_bestanden(zoek_term='test')
        zoeker.print_resultaten(test_bestanden, limit=3)

        # 6. CSV Export als er bestanden zijn
        if alle_bestanden:
            print("\n6️⃣ CSV EXPORT:")
            zoeker.export_naar_csv(alle_bestanden, 'alle_project_bestanden.csv')

        print("\n✅ Alle zoekfuncties succesvol uitgevoerd!")
        print("\n💡 GEBRUIK:")
        print("   - zoeker.zoek_alle_project_bestanden() - alle bestanden")
        print("   - zoeker.zoek_per_bestandstype('pdf') - specifiek type")
        print("   - zoeker.zoek_per_project(project_id) - specifiek project")
        print("   - zoeker.download_bestand(id, 'pad/bestand.ext') - download bestand")
        print("\n📝 OPMERKING: search.py toont alleen bestandslijsten.")
        print("   Voor downloads gebruik: text_search.py --download <id>")

    except Exception as e:
        print(f"❌ Hoofdfout: {e}")
        import traceback
        print(f"   Traceback: {traceback.format_exc()}")


if __name__ == "__main__":
    main()
