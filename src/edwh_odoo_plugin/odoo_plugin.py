from pathlib import Path
import edwh
from edwh import improved_task as task
from invoke import Context


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
        'verbose': 'Show detailed setup information'
    },
    hookable=True
)
def setup(c: Context,
          verbose=False):
    """
    Setup Odoo Plugin - Create .env configuration file for Odoo connection
    
    This will interactively prompt for Odoo connection details and create
    a .env file with the necessary configuration.
    
    Examples:
        edwh odoo.setup
        edwh odoo.setup --verbose
    """

    if verbose:
        print("🚀 Setting up Odoo Plugin")
        print("=" * 50)
    
    try:
        # Show where we're looking for .env files
        cwd_dotenv = Path.cwd() / '.env'
        config_dotenv = Path.home() / ".config/edwh/edwh_odoo_plugin.env"
        
        if verbose:
            print(f"\n🔍 Searching for .env configuration files:")
            print(f"   1. Current directory: {cwd_dotenv.absolute()}")
            print(f"   2. Config directory:  {config_dotenv.absolute()}")
        
        if cwd_dotenv.exists():
            # check local first
            dotenv_path = cwd_dotenv
            if verbose:
                print(f"✅ Found .env file in current directory")
            else:
                print(f"📁 Using .env file: {dotenv_path.absolute()}")
        else:
            # default to plugin folder as an escape
            dotenv_path = config_dotenv
            if not dotenv_path.exists():
                dotenv_path.parent.mkdir(parents=True, exist_ok=True)
                dotenv_path.touch()
                if verbose:
                    print(f"📝 Created new .env file in config directory")
                else:
                    print(f"📝 Created new .env file: {dotenv_path.absolute()}")
            else:
                if verbose:
                    print(f"✅ Found .env file in config directory")
                else:
                    print(f"📁 Using .env file: {dotenv_path.absolute()}")

        # Check existing configuration
        existing_config = {}
        if dotenv_path.exists():
            import os
            from dotenv import load_dotenv
            load_dotenv(dotenv_path)
            existing_config = {
                'host': os.getenv('ODOO_HOST', ''),
                'port': os.getenv('ODOO_PORT', ''),
                'protocol': os.getenv('ODOO_PROTOCOL', ''),
                'database': os.getenv('ODOO_DATABASE', ''),
                'user': os.getenv('ODOO_USER', ''),
                'password': os.getenv('ODOO_PASSWORD', '')
            }

        # Interactive setup for Odoo connection
        print("\n📋 Odoo Connection Setup")
        print("Please provide your Odoo connection details:")
        
        odoo_host = edwh.check_env(
            key="ODOO_HOST",
            default="your-odoo-instance.odoo.com",
            comment="Odoo server hostname (e.g., your-company.odoo.com)",
            env_path=dotenv_path,
        )
        
        odoo_port = edwh.check_env(
            key="ODOO_PORT",
            default="443",
            env_path=dotenv_path,
            comment="Odoo server port (443 for HTTPS, 80 for HTTP, 8069 for development)"
        )
        
        odoo_protocol = edwh.check_env(
            key="ODOO_PROTOCOL",
            default="xml-rpcs",
            comment="Odoo protocol (xml-rpcs for HTTPS, xml-rpc for HTTP)",
            env_path=dotenv_path,
            allowed_values=("xml-rpc", "xml-rpcs")
        )
        
        odoo_database = edwh.check_env(
            key="ODOO_DATABASE", 
            default="your-database-name",
            env_path=dotenv_path,
            comment="Odoo database name"
        )
        
        odoo_user = edwh.check_env(
            key="ODOO_USER",
            default="your-username@company.com",
            env_path=dotenv_path,
            comment="Odoo username/email"
        )
        
        odoo_password = edwh.check_env(
            key="ODOO_PASSWORD",
            default="",
            env_path=dotenv_path,
            comment="Odoo password"
        )
        
        if not odoo_password:
            print("❌ Error: Password is required for Odoo authentication")
            return {
                'success': False,
                'error': 'Password is required'
            }

        # Compare new configuration with existing
        new_config = {
            'host': odoo_host,
            'port': odoo_port,
            'protocol': odoo_protocol,
            'database': odoo_database,
            'user': odoo_user,
            'password': odoo_password
        }

        # Check if configuration has changed
        config_changed = False
        if existing_config:
            for key, value in new_config.items():
                if existing_config.get(key) != value:
                    config_changed = True
                    break
        else:
            config_changed = True  # No existing config means it's new

        if not config_changed:
            print("\n✅ Configuration already up to date - nothing changed!")
            print(f"📁 Current configuration in: {dotenv_path.absolute()}")
            print("\n📋 Current settings:")
            print(f"   Host: {odoo_host}")
            print(f"   Port: {odoo_port}")
            print(f"   Protocol: {odoo_protocol}")
            print(f"   Database: {odoo_database}")
            print(f"   User: {odoo_user}")
            print(f"   Password: {'*' * len(odoo_password) if odoo_password else '(not set)'}")
            
            return {
                'success': True,
                'message': 'Configuration already up to date',
                'changed': False,
                'config': {
                    'host': odoo_host,
                    'port': odoo_port,
                    'protocol': odoo_protocol,
                    'database': odoo_database,
                    'user': odoo_user
                }
            }

        # Test connection
        if verbose:
            print("\n🔍 Testing Odoo connection...")
            
        try:
            from .odoo_base import OdooBase
            test_connection = OdooBase(verbose=verbose)
            test_connection._connect()
            print("✅ Odoo connection test successful!")
        except Exception as conn_error:
            print(f"⚠️  Connection test failed: {conn_error}")
            if not edwh.confirm("Connection test failed. Continue anyway? [yN] "):
                return {
                    'success': False,
                    'error': f'Connection test failed: {conn_error}'
                }
        
        print(f"\n✅ Odoo plugin setup completed successfully!")
        print(f"📁 Configuration saved to: {dotenv_path.absolute()}")
        print(f"\n🚀 You can now use:")
        print(f"   edwh odoo.search 'your search term'")
        print(f"   edwh odoo.web")
        
        # Return success state for hookable tasks
        return {
            'success': True,
            'message': 'Odoo plugin setup completed successfully',
            'changed': True,
            'config': {
                'host': odoo_host,
                'port': odoo_port,
                'protocol': odoo_protocol,
                'database': odoo_database,
                'user': odoo_user
            }
        }
        
    except KeyboardInterrupt:
        print(f"\n🛑 Setup cancelled by user")
        return {
            'success': False,
            'error': 'Setup cancelled by user'
        }
    except Exception as e:
        print(f"❌ Setup error: {e}")
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
