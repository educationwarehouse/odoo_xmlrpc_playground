#!/usr/bin/env python3
"""
Task Manager - Subtask Moving and Hierarchy Management
=====================================================

Provides functionality for:
- Moving subtasks between parent tasks
- Promoting subtasks to main tasks
- Bulk operations on multiple subtasks
- Interactive task moving with search
- Task hierarchy visualization

Author: Based on odoo_base.py
Date: December 2024
"""

import re
from .odoo_base import OdooBase
from .text_search import OdooTextSearch


class TaskManager(OdooBase):
    """
    Task management functionality for moving subtasks and managing hierarchy
    """

    def __init__(self, verbose=False):
        """Initialize with .env configuration"""
        super().__init__(verbose=verbose)
        self.searcher = OdooTextSearch(verbose=verbose)

    def move_subtask(self, subtask_id, new_parent_id, target_project_id=None):
        """
        Move a subtask to a new parent task, optionally changing project
        
        Args:
            subtask_id: ID of the subtask to move
            new_parent_id: ID of the new parent task
            target_project_id: Optional project ID to move to
            
        Returns:
            dict: Result with success status and details
        """
        try:
            # Validate subtask exists
            subtask_records = self.tasks.search_records([('id', '=', subtask_id)])
            if not subtask_records:
                return {
                    'success': False,
                    'error': f'Subtask with ID {subtask_id} not found'
                }
            
            subtask = subtask_records[0]
            
            # Validate new parent exists
            parent_records = self.tasks.search_records([('id', '=', new_parent_id)])
            if not parent_records:
                return {
                    'success': False,
                    'error': f'Parent task with ID {new_parent_id} not found'
                }
            
            new_parent = parent_records[0]
            
            # Validate project if specified
            project_name = None
            if target_project_id:
                project_records = self.projects.search_records([('id', '=', target_project_id)])
                if not project_records:
                    return {
                        'success': False,
                        'error': f'Project with ID {target_project_id} not found'
                    }
                project_name = project_records[0].name
            
            # Check for circular dependency
            if self._would_create_circular_dependency(subtask_id, new_parent_id):
                return {
                    'success': False,
                    'error': 'Cannot move task: would create circular dependency'
                }
            
            # Prepare update values
            vals = {"parent_id": new_parent_id}
            if target_project_id is not None:
                vals["project_id"] = target_project_id
            
            if self.verbose:
                print(f"🔄 Moving subtask {subtask_id} to parent {new_parent_id}")
                if target_project_id:
                    print(f"   Also moving to project {target_project_id}")
            
            # Perform the move
            success = self.tasks.write([subtask_id], vals)
            
            if success:
                return {
                    'success': True,
                    'subtask_name': subtask.name,
                    'new_parent_name': new_parent.name,
                    'project_name': project_name
                }
            else:
                return {
                    'success': False,
                    'error': 'Write operation failed'
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def promote_task(self, task_id):
        """
        Promote a subtask to a main task (remove parent relationship)
        
        Args:
            task_id: ID of the task to promote
            
        Returns:
            dict: Result with success status and details
        """
        try:
            # Validate task exists
            task_records = self.tasks.search_records([('id', '=', task_id)])
            if not task_records:
                return {
                    'success': False,
                    'error': f'Task with ID {task_id} not found'
                }
            
            task = task_records[0]
            
            # Check if task has a parent
            if not hasattr(task, 'parent_id') or not task.parent_id:
                return {
                    'success': False,
                    'error': 'Task is already a main task (no parent)'
                }
            
            former_parent_name = task.parent_id.name if hasattr(task.parent_id, 'name') else 'Unknown'
            
            if self.verbose:
                print(f"⬆️ Promoting task {task_id} to main task")
                print(f"   Removing parent: {former_parent_name}")
            
            # Remove parent relationship
            success = self.tasks.write([task_id], {"parent_id": False})
            
            if success:
                return {
                    'success': True,
                    'task_name': task.name,
                    'former_parent_name': former_parent_name
                }
            else:
                return {
                    'success': False,
                    'error': 'Write operation failed'
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def move_multiple_subtasks(self, subtask_ids, new_parent_id, target_project_id=None):
        """
        Move multiple subtasks to a new parent task
        
        Args:
            subtask_ids: List of subtask IDs to move
            new_parent_id: ID of the new parent task
            target_project_id: Optional project ID to move to
            
        Returns:
            dict: Result with success status and details
        """
        try:
            # Validate new parent exists
            parent_records = self.tasks.search_records([('id', '=', new_parent_id)])
            if not parent_records:
                return {
                    'success': False,
                    'error': f'Parent task with ID {new_parent_id} not found'
                }
            
            new_parent = parent_records[0]
            
            # Validate project if specified
            if target_project_id:
                project_records = self.projects.search_records([('id', '=', target_project_id)])
                if not project_records:
                    return {
                        'success': False,
                        'error': f'Project with ID {target_project_id} not found'
                    }
            
            moved_count = 0
            failed_count = 0
            errors = []
            
            for subtask_id in subtask_ids:
                try:
                    # Check for circular dependency
                    if self._would_create_circular_dependency(subtask_id, new_parent_id):
                        errors.append(f'Task {subtask_id}: would create circular dependency')
                        failed_count += 1
                        continue
                    
                    # Validate subtask exists
                    subtask_records = self.tasks.search_records([('id', '=', subtask_id)])
                    if not subtask_records:
                        errors.append(f'Task {subtask_id}: not found')
                        failed_count += 1
                        continue
                    
                    # Prepare update values
                    vals = {"parent_id": new_parent_id}
                    if target_project_id is not None:
                        vals["project_id"] = target_project_id
                    
                    # Perform the move
                    success = self.tasks.write([subtask_id], vals)
                    
                    if success:
                        moved_count += 1
                        if self.verbose:
                            print(f"✅ Moved task {subtask_id}")
                    else:
                        errors.append(f'Task {subtask_id}: write operation failed')
                        failed_count += 1
                        
                except Exception as e:
                    errors.append(f'Task {subtask_id}: {str(e)}')
                    failed_count += 1
            
            return {
                'success': moved_count > 0,
                'moved_count': moved_count,
                'failed_count': failed_count,
                'errors': errors,
                'new_parent_name': new_parent.name
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def interactive_move(self, search_term=None):
        """
        Interactive task moving with search functionality
        
        Args:
            search_term: Optional initial search term
            
        Returns:
            dict: Result with success status
        """
        try:
            print("🔍 Interactive Task Mover")
            print("=" * 40)
            
            # Step 1: Find subtask to move
            if search_term:
                print(f"Searching for tasks with: '{search_term}'")
                results = self.searcher.search_tasks(search_term, limit=10)
            else:
                search_input = input("Enter search term to find subtask to move: ").strip()
                if not search_input:
                    return {'success': False, 'error': 'No search term provided'}
                results = self.searcher.search_tasks(search_input, limit=10)
            
            if not results:
                print("❌ No tasks found")
                return {'success': False, 'error': 'No tasks found'}
            
            # Display found tasks
            print(f"\n📋 Found {len(results)} tasks:")
            for i, task in enumerate(results, 1):
                parent_info = ""
                if task.get('parent_id'):
                    parent_info = f" (parent: {task.get('parent_name', 'Unknown')})"
                print(f"  {i}. {task['name']} (ID: {task['id']}){parent_info}")
            
            # Select subtask
            while True:
                try:
                    choice = input(f"\nSelect subtask to move (1-{len(results)}): ").strip()
                    if not choice:
                        return {'success': False, 'error': 'No selection made'}
                    
                    choice_idx = int(choice) - 1
                    if 0 <= choice_idx < len(results):
                        selected_task = results[choice_idx]
                        break
                    else:
                        print(f"❌ Please enter a number between 1 and {len(results)}")
                except ValueError:
                    print("❌ Please enter a valid number")
            
            # Step 2: Find new parent
            parent_search = input(f"\nEnter search term to find new parent task: ").strip()
            if not parent_search:
                return {'success': False, 'error': 'No parent search term provided'}
            
            parent_results = self.searcher.search_tasks(parent_search, limit=10)
            if not parent_results:
                print("❌ No parent tasks found")
                return {'success': False, 'error': 'No parent tasks found'}
            
            # Display potential parents
            print(f"\n📋 Found {len(parent_results)} potential parent tasks:")
            for i, task in enumerate(parent_results, 1):
                print(f"  {i}. {task['name']} (ID: {task['id']})")
            
            # Select parent
            while True:
                try:
                    choice = input(f"\nSelect new parent task (1-{len(parent_results)}): ").strip()
                    if not choice:
                        return {'success': False, 'error': 'No parent selection made'}
                    
                    choice_idx = int(choice) - 1
                    if 0 <= choice_idx < len(parent_results):
                        selected_parent = parent_results[choice_idx]
                        break
                    else:
                        print(f"❌ Please enter a number between 1 and {len(parent_results)}")
                except ValueError:
                    print("❌ Please enter a valid number")
            
            # Step 3: Optional project change
            project_id = None
            change_project = input(f"\nChange project? (y/N): ").strip().lower()
            if change_project in ['y', 'yes']:
                project_search = input("Enter search term to find project: ").strip()
                if project_search:
                    project_results = self.searcher.search_projects(project_search, limit=10)
                    if project_results:
                        print(f"\n📂 Found {len(project_results)} projects:")
                        for i, project in enumerate(project_results, 1):
                            print(f"  {i}. {project['name']} (ID: {project['id']})")
                        
                        while True:
                            try:
                                choice = input(f"\nSelect project (1-{len(project_results)}): ").strip()
                                if not choice:
                                    break
                                
                                choice_idx = int(choice) - 1
                                if 0 <= choice_idx < len(project_results):
                                    project_id = project_results[choice_idx]['id']
                                    break
                                else:
                                    print(f"❌ Please enter a number between 1 and {len(project_results)}")
                            except ValueError:
                                print("❌ Please enter a valid number")
            
            # Step 4: Confirm and execute
            print(f"\n📋 MOVE CONFIRMATION")
            print(f"   Subtask: {selected_task['name']} (ID: {selected_task['id']})")
            print(f"   New parent: {selected_parent['name']} (ID: {selected_parent['id']})")
            if project_id:
                project_name = next(p['name'] for p in project_results if p['id'] == project_id)
                print(f"   New project: {project_name} (ID: {project_id})")
            
            confirm = input(f"\nProceed with move? (y/N): ").strip().lower()
            if confirm not in ['y', 'yes']:
                return {'success': False, 'error': 'Move cancelled by user'}
            
            # Execute the move
            result = self.move_subtask(selected_task['id'], selected_parent['id'], project_id)
            
            if result['success']:
                print(f"\n✅ Task moved successfully!")
            else:
                print(f"\n❌ Move failed: {result['error']}")
            
            return result
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def show_hierarchy(self, task_id, max_depth=3):
        """
        Show task hierarchy for a given task
        
        Args:
            task_id: ID of the task to show hierarchy for
            max_depth: Maximum depth to traverse
            
        Returns:
            dict: Result with hierarchy data
        """
        try:
            # Get the main task
            task_records = self.tasks.search_records([('id', '=', task_id)])
            if not task_records:
                return {
                    'success': False,
                    'error': f'Task with ID {task_id} not found'
                }
            
            main_task = task_records[0]
            
            # Build hierarchy
            hierarchy = {
                'main_task': self._task_to_dict(main_task),
                'parents': self._get_parent_chain(task_id),
                'children': self._get_children_recursive(task_id, max_depth)
            }
            
            return {
                'success': True,
                'hierarchy': hierarchy
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def print_hierarchy(self, hierarchy):
        """Print task hierarchy in a tree format"""
        # Print parent chain
        if hierarchy['parents']:
            print("📈 PARENT CHAIN:")
            for i, parent in enumerate(hierarchy['parents']):
                indent = "  " * i
                print(f"{indent}└── {parent['name']} (ID: {parent['id']})")
        
        # Print main task
        print(f"\n🎯 MAIN TASK:")
        main = hierarchy['main_task']
        print(f"└── {main['name']} (ID: {main['id']})")
        if main.get('project_name'):
            print(f"    📂 Project: {main['project_name']}")
        if main.get('user'):
            print(f"    👤 Assigned: {main['user']}")
        
        # Print children
        if hierarchy['children']:
            print(f"\n📉 SUBTASKS:")
            self._print_children_recursive(hierarchy['children'], "")

    def _print_children_recursive(self, children, indent):
        """Recursively print children with proper indentation"""
        for i, child in enumerate(children):
            is_last = i == len(children) - 1
            current_indent = "└──" if is_last else "├──"
            print(f"{indent}{current_indent} {child['name']} (ID: {child['id']})")
            
            if child.get('children'):
                next_indent = indent + ("   " if is_last else "│  ")
                self._print_children_recursive(child['children'], next_indent)

    def _would_create_circular_dependency(self, subtask_id, new_parent_id):
        """Check if moving subtask would create circular dependency"""
        if subtask_id == new_parent_id:
            return True
        
        # Check if new_parent_id is a descendant of subtask_id
        return self._is_descendant(subtask_id, new_parent_id)

    def _is_descendant(self, ancestor_id, potential_descendant_id):
        """Check if potential_descendant_id is a descendant of ancestor_id"""
        try:
            current_id = potential_descendant_id
            visited = set()
            
            while current_id and current_id not in visited:
                visited.add(current_id)
                
                task_records = self.tasks.search_records([('id', '=', current_id)])
                if not task_records:
                    break
                
                task = task_records[0]
                if hasattr(task, 'parent_id') and task.parent_id:
                    parent_id = task.parent_id.id if hasattr(task.parent_id, 'id') else task.parent_id
                    if parent_id == ancestor_id:
                        return True
                    current_id = parent_id
                else:
                    break
            
            return False
            
        except Exception:
            return False

    def _get_parent_chain(self, task_id):
        """Get chain of parent tasks"""
        parents = []
        current_id = task_id
        visited = set()
        
        try:
            while current_id and current_id not in visited:
                visited.add(current_id)
                
                task_records = self.tasks.search_records([('id', '=', current_id)])
                if not task_records:
                    break
                
                task = task_records[0]
                if hasattr(task, 'parent_id') and task.parent_id:
                    parent_id = task.parent_id.id if hasattr(task.parent_id, 'id') else task.parent_id
                    parent_records = self.tasks.search_records([('id', '=', parent_id)])
                    if parent_records:
                        parents.insert(0, self._task_to_dict(parent_records[0]))
                        current_id = parent_id
                    else:
                        break
                else:
                    break
                    
        except Exception as e:
            if self.verbose:
                print(f"⚠️ Error getting parent chain: {e}")
        
        return parents

    def _get_children_recursive(self, task_id, max_depth, current_depth=0):
        """Get children recursively up to max_depth"""
        if current_depth >= max_depth:
            return []

        children = []

        try:
            if self.verbose:
                print(f"🔍 Looking for children of task {task_id} at depth {current_depth}")

            # Use the working method: Direct parent_id search with integer task_id
            child_records = self.tasks.search_records([('parent_id', '=', int(task_id))])
            
            if self.verbose:
                print(f"   Method 1 (parent_id = {task_id}): Found {len(child_records)} children")
                if child_records:
                    for child in child_records:
                        print(f"     Child: {child.name} (ID: {child.id})")

            # Process found children
            for child in child_records:
                child_dict = self._task_to_dict(child)

                # Get grandchildren recursively
                if current_depth + 1 < max_depth:
                    child_dict['children'] = self._get_children_recursive(
                        child.id, max_depth, current_depth + 1
                    )

                children.append(child_dict)

        except Exception as e:
            if self.verbose:
                print(f"⚠️ Error getting children for task {task_id}: {e}")

        if self.verbose:
            print(f"   Final result: {len(children)} children for task {task_id}")

        return children

    def show_project_hierarchy(self, project_id, max_depth=3):
        """
        Show complete project hierarchy with all tasks and their subtasks
        
        Args:
            project_id: ID of the project to show hierarchy for
            max_depth: Maximum depth to traverse for task subtasks
            
        Returns:
            dict: Result with project hierarchy data
        """
        try:
            # Get the project
            project_records = self.projects.search_records([('id', '=', project_id)])
            if not project_records:
                return {
                    'success': False,
                    'error': f'Project with ID {project_id} not found'
                }
            
            project = project_records[0]
            
            if self.verbose:
                print(f"🔍 Searching for tasks in project {project_id} ('{project.name}')")
            
            # Get all tasks in this project - use the working approach
            all_tasks = self.tasks.search_records([('project_id', '=', int(project_id))])
            
            if self.verbose:
                print(f"🔍 Found {len(all_tasks)} tasks in project {project_id}")
            
            # Separate main tasks (no parent) from subtasks
            main_tasks = []
            all_task_ids = set()
            
            for task in all_tasks:
                all_task_ids.add(task.id)
                # Check if task has no parent (is a main task)
                if not hasattr(task, 'parent_id') or not task.parent_id:
                    main_tasks.append(task)
                    if self.verbose:
                        print(f"   Main task: {task.name} (ID: {task.id})")
            
            if self.verbose:
                print(f"🔍 Found {len(main_tasks)} main tasks (without parents)")
            
            # Build hierarchy for each main task
            project_hierarchy = {
                'project': self._project_to_dict(project),
                'main_tasks': [],
                'total_tasks': len(all_tasks),
                'main_task_count': len(main_tasks)
            }
            
            for main_task in main_tasks:
                task_dict = self._task_to_dict(main_task)
                
                # Get children recursively
                task_dict['children'] = self._get_children_recursive(main_task.id, max_depth)
                
                project_hierarchy['main_tasks'].append(task_dict)
            
            return {
                'success': True,
                'hierarchy': project_hierarchy
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def print_project_hierarchy(self, hierarchy):
        """Print project hierarchy as one unified tree"""
        project = hierarchy['project']
        
        # Print project as root of the tree
        print(f"📂 {project['name']} (ID: {project['id']})")
        
        # Print project details with tree indentation
        if project.get('description'):
            desc = project['description'][:100] + '...' if len(project['description']) > 100 else project['description']
            print(f"│  📝 {desc}")
        if project.get('partner_name'):
            print(f"│  🏢 Client: {project['partner_name']}")
        if project.get('user_name'):
            print(f"│  👤 Manager: {project['user_name']}")
        if project.get('stage_name'):
            print(f"│  📊 Stage: {project['stage_name']}")
        
        # Print summary
        print(f"│  📊 Summary: {hierarchy['total_tasks']} tasks ({hierarchy['main_task_count']} main, {hierarchy['total_tasks'] - hierarchy['main_task_count']} subtasks)")
        
        # Print main tasks and their hierarchies as part of the project tree
        if hierarchy['main_tasks']:
            for i, main_task in enumerate(hierarchy['main_tasks']):
                is_last_main = i == len(hierarchy['main_tasks']) - 1
                main_prefix = "└──" if is_last_main else "├──"
                
                print(f"{main_prefix} {main_task['name']} (ID: {main_task['id']})")
                
                # Print task details
                if main_task.get('user'):
                    indent = "   " if is_last_main else "│  "
                    print(f"{indent} 👤 {main_task['user']}")
                
                # Print children
                if main_task.get('children'):
                    child_indent = "   " if is_last_main else "│  "
                    self._print_children_recursive(main_task['children'], child_indent)
        else:
            print(f"└── 📭 No tasks found in this project")

    def _project_to_dict(self, project):
        """Convert project record to dictionary"""
        project_dict = {
            'id': project.id,
            'name': getattr(project, 'name', f'Project {project.id}'),
        }
        
        # Add description
        if hasattr(project, 'description') and project.description:
            project_dict['description'] = project.description
        
        # Add partner info
        if hasattr(project, 'partner_id') and project.partner_id:
            try:
                project_dict['partner_name'] = project.partner_id.name if hasattr(project.partner_id, 'name') else 'Unknown'
                project_dict['partner_id'] = project.partner_id.id if hasattr(project.partner_id, 'id') else project.partner_id
            except:
                pass
        
        # Add user info
        if hasattr(project, 'user_id') and project.user_id:
            try:
                project_dict['user_name'] = project.user_id.name if hasattr(project.user_id, 'name') else 'Unknown'
                project_dict['user_id'] = project.user_id.id if hasattr(project.user_id, 'id') else project.user_id
            except:
                pass
        
        # Add stage info
        if hasattr(project, 'stage_id') and project.stage_id:
            try:
                project_dict['stage_name'] = project.stage_id.name if hasattr(project.stage_id, 'name') else 'Unknown'
                project_dict['stage_id'] = project.stage_id.id if hasattr(project.stage_id, 'id') else project.stage_id
            except:
                pass
        
        return project_dict

    def _task_to_dict(self, task):
        """Convert task record to dictionary"""
        task_dict = {
            'id': task.id,
            'name': getattr(task, 'name', f'Task {task.id}'),
        }
        
        # Add project info
        if hasattr(task, 'project_id') and task.project_id:
            try:
                task_dict['project_name'] = task.project_id.name if hasattr(task.project_id, 'name') else 'Unknown'
                task_dict['project_id'] = task.project_id.id if hasattr(task.project_id, 'id') else task.project_id
            except:
                pass
        
        # Add user info
        user_id, user_name = self.extract_user_from_task(task)
        if user_name != 'Unassigned':
            task_dict['user'] = user_name
            task_dict['user_id'] = user_id
        
        # Add stage info
        if hasattr(task, 'stage_id') and task.stage_id:
            try:
                task_dict['stage_name'] = task.stage_id.name if hasattr(task.stage_id, 'name') else 'Unknown'
                task_dict['stage_id'] = task.stage_id.id if hasattr(task.stage_id, 'id') else task.stage_id
            except:
                pass
        
        # Add priority
        if hasattr(task, 'priority'):
            task_dict['priority'] = getattr(task, 'priority', '0')
        
        return task_dict
