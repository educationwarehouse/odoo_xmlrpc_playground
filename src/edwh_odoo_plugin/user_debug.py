#!/usr/bin/env python3
"""
User Debug Tool - Focus on User Data Retrieval
==============================================

Quick experiments to understand user ID mapping and retrieval issues.
Specifically looking at:
- User 8 (Remco) 
- User 2909 vs User 13 (Rien) mapping issue
- Different ways to access user fields

Author: Debug tool
Date: August 2025
"""

import os
import re
from .odoo_base import OdooBase
import warnings

# Suppress the pkg_resources deprecation warning from odoo_rpc_client globally
warnings.filterwarnings("ignore", 
                      message="pkg_resources is deprecated as an API.*",
                      category=UserWarning)


class UserDebugTool(OdooBase):
    """
    Focused tool for debugging user data retrieval
    """

    def __init__(self, verbose=True):
        """Initialize with verbose output by default"""
        super().__init__(verbose=verbose)

    def get_all_users(self):
        """Get all users and show their details"""
        print("👥 ALL USERS IN SYSTEM")
        print("=" * 50)
        
        try:
            users = self.client['res.users'].search_records([])
            print(f"Found {len(users)} users:")
            
            for user in users:
                print(f"  ID: {user.id:3} | Name: {user.name}")
            
            return users
            
        except Exception as e:
            print(f"❌ Error getting users: {e}")
            return []

    def get_user_details(self, user_id):
        """Get detailed info about a specific user"""
        print(f"\n🔍 USER {user_id} DETAILS")
        print("=" * 30)
        
        try:
            # Method 1: Browse by ID
            user = self.client['res.users'].browse(user_id)
            print(f"Browse method:")
            print(f"  ID: {user.id}")
            print(f"  Name: {user.name}")
            print(f"  Login: {getattr(user, 'login', 'N/A')}")
            print(f"  Email: {getattr(user, 'email', 'N/A')}")
            print(f"  Active: {getattr(user, 'active', 'N/A')}")
            
            # Method 2: Search records
            user_records = self.client['res.users'].search_records([('id', '=', user_id)])
            if user_records:
                user_rec = user_records[0]
                print(f"\nSearch records method:")
                print(f"  ID: {user_rec.id}")
                print(f"  Name: {user_rec.name}")
                print(f"  Login: {getattr(user_rec, 'login', 'N/A')}")
            else:
                print(f"\n❌ No user found with ID {user_id} via search_records")
            
            # Method 3: Read method
            user_data = self.client['res.users'].read(user_id, ['name', 'login', 'email', 'active'])
            print(f"\nRead method:")
            print(f"  Data: {user_data}")
            
            return user
            
        except Exception as e:
            print(f"❌ Error getting user {user_id}: {e}")
            return None

    def test_task_user_fields(self, task_id=2909):
        """Test different ways to access user fields on a task"""
        print(f"\n🔍 TASK {task_id} USER FIELD ANALYSIS")
        print("=" * 40)
        
        try:
            # Get the task
            task = self.tasks.browse(task_id)
            print(f"Task: {task.name}")
            
            # Use shared user extraction method
            print(f"\n--- Using shared user extraction method ---")
            try:
                user_id, user_name = self.extract_user_from_task(task)
                print(f"  ✅ Extracted user ID: {user_id}")
                print(f"  ✅ Extracted user name: {user_name}")
            except Exception as extract_error:
                print(f"  ❌ Error with shared extraction: {extract_error}")
            
            # Test all possible user field names for comparison
            user_fields = ['user_id', 'user_ids', 'assigned_user_id', 'responsible_user_id', 
                          'assignee_id', 'owner_id', 'create_uid', 'write_uid']
            
            for field_name in user_fields:
                print(f"\n--- Testing field: {field_name} ---")
                
                if hasattr(task, field_name):
                    try:
                        field_value = getattr(task, field_name, None)
                        print(f"  ✅ Field exists: {field_name}")
                        print(f"  Type: {type(field_value)}")
                        print(f"  Value: {field_value}")
                        print(f"  String repr: {str(field_value)}")
                        
                        # Try to extract ID if it's a partial object
                        if str(field_value).startswith('functools.partial'):
                            partial_str = str(field_value)
                            id_match = re.search(r'\[(\d+)\]', partial_str)
                            if id_match:
                                extracted_id = int(id_match.group(1))
                                print(f"  🔍 Extracted ID: {extracted_id}")
                                
                                # Look up this user
                                if extracted_id != task_id:  # Skip if it's the task ID itself
                                    user_info = self.get_user_details(extracted_id)
                                    if user_info:
                                        print(f"  👤 User name: {user_info.name}")
                                else:
                                    print(f"  ⚠️ Extracted ID matches task ID - wrong field")
                        
                        # Try direct access if it has an id attribute
                        elif hasattr(field_value, 'id'):
                            print(f"  🔍 Direct ID access: {field_value.id}")
                            user_info = self.get_user_details(field_value.id)
                            if user_info:
                                print(f"  👤 User name: {user_info.name}")
                        
                        # If it's an integer
                        elif isinstance(field_value, int):
                            print(f"  🔍 Integer ID: {field_value}")
                            user_info = self.get_user_details(field_value)
                            if user_info:
                                print(f"  👤 User name: {user_info.name}")
                        
                    except Exception as field_error:
                        print(f"  ❌ Error accessing {field_name}: {field_error}")
                else:
                    print(f"  ❌ Field does not exist: {field_name}")
            
            # Try read method on task
            print(f"\n--- Task read method ---")
            try:
                task_data = self.tasks.read(task_id, ['name', 'user_id', 'user_ids', 'create_uid', 'write_uid'])
                print(f"Task data: {task_data}")
            except Exception as read_error:
                print(f"❌ Read method error: {read_error}")
                
        except Exception as e:
            print(f"❌ Error analyzing task {task_id}: {e}")

    def check_user_mapping(self):
        """Check if user 2909 should actually be user 13 (Rien)"""
        print(f"\n🔍 USER MAPPING ANALYSIS")
        print("=" * 30)
        
        # Check if user 2909 exists
        print("Checking user 2909:")
        user_2909 = self.get_user_details(2909)
        
        # Check user 13 (suspected to be Rien)
        print("\nChecking user 13:")
        user_13 = self.get_user_details(13)
        
        # Check user 8 (you - Remco)
        print("\nChecking user 8 (Remco):")
        user_8 = self.get_user_details(8)
        
        # Look for users with "Rien" in the name
        print("\nSearching for users with 'Rien' in name:")
        try:
            rien_users = self.client['res.users'].search_records([('name', 'ilike', 'rien')])
            for user in rien_users:
                print(f"  Found: ID {user.id} - {user.name}")
        except Exception as e:
            print(f"❌ Error searching for Rien: {e}")

    def run_full_debug(self):
        """Run all debug tests"""
        print("🚀 USER DEBUG TOOL")
        print("=" * 50)
        
        # 1. Get all users
        users = self.get_all_users()
        
        # 2. Check specific users
        self.get_user_details(8)   # Remco
        self.get_user_details(13)  # Suspected Rien
        self.get_user_details(2909) # The problematic ID
        
        # 3. Test task user fields
        self.test_task_user_fields(2909)
        
        # 4. Check user mapping
        self.check_user_mapping()
        
        print(f"\n✅ Debug analysis complete!")


def main():
    """Main function"""
    try:
        debugger = UserDebugTool()
        debugger.run_full_debug()
        
    except Exception as e:
        print(f"❌ Debug error: {e}")
        import traceback
        print(f"   Traceback: {traceback.format_exc()}")


if __name__ == "__main__":
    main()
