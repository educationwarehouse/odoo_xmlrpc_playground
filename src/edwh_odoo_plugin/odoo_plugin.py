from edwh import improved_task as task
from invoke import Context
import threading
import webbrowser
import time

@task(
    help={
        'search_term': 'Required text to search for',
        'since': 'Time reference (e.g., "1 week", "3 days", "2 months")',
        'type': 'What to search in: all, projects, tasks, logs, files (default: all)',
        'no_logs': 'Exclude search in log messages (logs included by default)',
        'no_files': 'Exclude search in file names and metadata (files included by default)',
        'files_only': 'Search only in files (equivalent to --type files)',
        'file_types': 'Filter by file types/extensions (comma-separated, e.g., "pdf,docx,png")',
        'no_descriptions': 'Do not search in descriptions, only names/subjects',
        'limit': 'Limit number of results to display',
        'export': 'Export results to CSV file',
        'download': 'Download file by ID (use with search results)',
        'download_path': 'Directory to download files to (default: ./downloads/)',
        'stats': 'Show file statistics (when files are included)',
        'verbose': 'Show detailed search information and debug output'
    }, 
    positional=['search_term'],
    hookable=True
)
def search(c: Context, 
          search_term,
          since=None,
          type='all',
          no_logs=False,
          no_files=False,
          files_only=False,
          file_types=None,
          no_descriptions=False,
          limit=None,
          export=None,
          download=None,
          download_path='./downloads/',
          stats=False,
          verbose=False):
    """
    Odoo Project Text Search - Search through projects, tasks, and logs
    
    Examples:
        edwh odoo.search "bug fix" --since "1 week"
        edwh odoo.search "client meeting" --since "3 days" --type projects
        edwh odoo.search "error" --since "2 weeks" --no-logs
        edwh odoo.search "urgent" --type tasks --no-descriptions
        edwh odoo.search "report" --file-types "pdf,docx" --stats
        edwh odoo.search --download 12345 --download-path ./my_files/
    """
    from .text_search import OdooTextSearch
    import os
    
    # Validate search type
    valid_types = ['all', 'projects', 'tasks', 'logs', 'files']
    if type not in valid_types:
        print(f"❌ Error: Invalid search type '{type}'. Valid types are: {', '.join(valid_types)}")
        return
    
    # Handle files-only flag
    if files_only:
        type = 'files'
        no_files = False
    
    # Handle download request
    if download:
        try:
            searcher = OdooTextSearch(verbose=verbose)
            filename = f"file_{download}"
            output_path = os.path.join(download_path, filename)
            success = searcher.download_file(download, output_path)
            if success:
                print(f"✅ Download completed!")
            return
        except Exception as e:
            print(f"❌ Download error: {e}")
            return
    
    # Check if search_term is provided when not downloading
    if not search_term:
        print("❌ Error: search_term is required unless using --download")
        return
    
    # Parse file types if provided
    file_types_list = None
    if file_types:
        file_types_list = [ft.strip() for ft in file_types.split(',')]
    
    if verbose:
        print("🚀 Odoo Project Text Search")
        print("=" * 50)
    
    try:
        # Initialize searcher
        searcher = OdooTextSearch(verbose=verbose)
        
        # Perform search
        results = searcher.full_text_search(
            search_term=search_term,
            since=since,
            search_type=type,
            include_descriptions=not no_descriptions,
            include_logs=not no_logs,
            include_files=not no_files or type == 'files',
            file_types=file_types_list,
            limit=int(limit) if limit else None
        )
        
        # Print results
        searcher.print_results(results, limit=int(limit) if limit else None)
        
        # Show file statistics if requested and files are included
        if stats and results.get('files'):
            searcher.print_file_statistics(results['files'])
        
        # Export if requested
        if export:
            searcher.export_results(results, export)
        
        print(f"\n✅ Search completed successfully!")
        
        # Return results for potential use by other tasks (EDWH hookable pattern)
        return {
            'success': True,
            'results': results,
            'total_found': sum(len(results.get(key, [])) for key in ['projects', 'tasks', 'messages', 'files'])
        }
        
    except Exception as e:
        print(f"❌ Error: {e}")
        if verbose:
            import traceback
            print(f"   Traceback: {traceback.format_exc()}")
        
        # Return error state for hookable tasks
        return {
            'success': False,
            'error': str(e)
        }


@task(
    help={
        'host': 'Host to bind to (default: localhost)',
        'port': 'Port to bind to (default: 1900)',
        'browser': 'Open browser automatically (default: False)',
        'verbose': 'Show detailed server information'
    },
    hookable=True
)
def web(c: Context,
        host='localhost',
        port=1900,
        browser=False,
        verbose=False):
    """
    Start Odoo Web Search Server - Web interface for Odoo text search
    
    Examples:
        edwh odoo.web
        edwh odoo.web --port 8080 --host 0.0.0.0
        edwh odoo.web --browser
    """
    from .web_search_server import WebSearchServer
    import os
    
    if verbose:
        print("🚀 Starting Odoo Web Search Server")
        print("=" * 50)
    
    # Check if .env file exists
    if not os.path.exists('.env'):
        print("⚠️  No .env file found. You can configure settings through the web interface.")
        print("   Or create a .env file with your Odoo credentials.")
    
    try:
        # Start server
        server = WebSearchServer(host=host, port=int(port))
        server.start(open_browser=browser)
        
        return {
            'success': True,
            'message': 'Server started successfully',
            'host': host,
            'port': port
        }
        
    except KeyboardInterrupt:
        print(f"\n🛑 Server stopped by user")
        return {
            'success': True,
            'message': 'Server stopped by user'
        }
    except Exception as e:
        print(f"❌ Server error: {e}")
        if verbose:
            import traceback
            print(f"   Traceback: {traceback.format_exc()}")
        
        return {
            'success': False,
            'error': str(e)
        }
