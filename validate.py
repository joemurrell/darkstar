#!/usr/bin/env python3
"""
Validation script for DarkstarAIC multi-server functionality
Tests the new features without requiring Discord/OpenAI connections
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """Test that all required modules can be imported"""
    print("Testing imports...")
    try:
        import discord
        from discord import app_commands
        from openai import OpenAI
        from fuzzywuzzy import fuzz
        print("  ✓ All required modules imported successfully")
        return True
    except ImportError as e:
        print(f"  ✗ Import failed: {e}")
        return False

def test_module_structure():
    """Test that app.py has the expected structure"""
    print("\nTesting module structure...")
    try:
        with open('app.py', 'r') as f:
            content = f.read()
        
        # Check for new features
        required_elements = [
            'GUILD_ASSISTANTS',
            'get_or_create_guild_assistant',
            'setup_command',
            'upload_document_command',
            'list_documents_command',
            'remove_document_command',
            'guild_id',  # Should be used in functions
        ]
        
        missing = []
        for element in required_elements:
            if element not in content:
                missing.append(element)
        
        if missing:
            print(f"  ✗ Missing required elements: {', '.join(missing)}")
            return False
        
        print("  ✓ All required elements found")
        
        # Check command decorators
        commands = [
            '@tree.command(name="setup"',
            '@tree.command(name="upload_document"',
            '@tree.command(name="list_documents"',
            '@tree.command(name="remove_document"',
            '@tree.command(name="ask"',
            '@tree.command(name="quiz_start"',
        ]
        
        missing_commands = []
        for cmd in commands:
            if cmd not in content:
                missing_commands.append(cmd)
        
        if missing_commands:
            print(f"  ✗ Missing commands: {', '.join(missing_commands)}")
            return False
        
        print("  ✓ All commands defined")
        
        # Check for admin permissions on admin commands
        admin_commands = ['setup_command', 'upload_document_command', 'remove_document_command']
        for cmd in admin_commands:
            # Find the function definition
            cmd_start = content.find(f'async def {cmd}')
            if cmd_start == -1:
                print(f"  ✗ Command {cmd} not found")
                return False
            
            # Check for @app_commands.default_permissions before the function
            section = content[max(0, cmd_start-200):cmd_start]
            if '@app_commands.default_permissions(administrator=True)' not in section:
                print(f"  ✗ Command {cmd} missing admin permission decorator")
                return False
        
        print("  ✓ Admin commands have proper permissions")
        
        return True
        
    except Exception as e:
        print(f"  ✗ Error reading module: {e}")
        return False

def test_documentation():
    """Test that documentation is updated"""
    print("\nTesting documentation...")
    try:
        with open('README.md', 'r') as f:
            readme = f.read()
        
        required_sections = [
            'Multi-Server',
            '/setup',
            '/upload_document',
            '/list_documents',
            '/remove_document',
            'Squadron SOP',
        ]
        
        missing = []
        for section in required_sections:
            if section not in readme:
                missing.append(section)
        
        if missing:
            print(f"  ✗ Missing documentation sections: {', '.join(missing)}")
            return False
        
        print("  ✓ README.md updated with new features")
        
        # Check for multi-server guide
        if os.path.exists('MULTI_SERVER_GUIDE.md'):
            print("  ✓ Multi-server guide exists")
        else:
            print("  ⚠ Multi-server guide not found (optional)")
        
        return True
        
    except Exception as e:
        print(f"  ✗ Error reading documentation: {e}")
        return False

def test_environment_handling():
    """Test that environment variables are handled correctly"""
    print("\nTesting environment variable handling...")
    try:
        with open('app.py', 'r') as f:
            content = f.read()
        
        # Check that ASSISTANT_ID uses .get() with default
        if 'os.environ.get("ASSISTANT_ID"' in content or "os.environ.get('ASSISTANT_ID'" in content:
            print("  ✓ ASSISTANT_ID uses .get() with default")
        else:
            print("  ✗ ASSISTANT_ID should use os.environ.get() for optional handling")
            return False
        
        # Check that required vars still use direct access
        if 'os.environ["DISCORD_TOKEN"]' in content:
            print("  ✓ DISCORD_TOKEN still required")
        else:
            print("  ✗ DISCORD_TOKEN should remain required")
            return False
        
        if 'os.environ["OPENAI_API_KEY"]' in content:
            print("  ✓ OPENAI_API_KEY still required")
        else:
            print("  ✗ OPENAI_API_KEY should remain required")
            return False
        
        return True
        
    except Exception as e:
        print(f"  ✗ Error checking environment handling: {e}")
        return False

def test_backward_compatibility():
    """Test that backward compatibility is maintained"""
    print("\nTesting backward compatibility...")
    try:
        with open('app.py', 'r') as f:
            content = f.read()
        
        # Check that global ASSISTANT_ID is still supported
        if 'if ASSISTANT_ID:' in content:
            print("  ✓ Global ASSISTANT_ID still supported")
        else:
            print("  ✗ Should maintain support for global ASSISTANT_ID")
            return False
        
        # Check that existing commands still work
        existing_commands = [
            'ask_command',
            'quiz_start',
            'quiz_answer',
            'quiz_end',
            'quiz_score',
            'info_command',
        ]
        
        for cmd in existing_commands:
            if f'async def {cmd}' not in content:
                print(f"  ✗ Existing command {cmd} not found")
                return False
        
        print("  ✓ All existing commands preserved")
        
        return True
        
    except Exception as e:
        print(f"  ✗ Error checking backward compatibility: {e}")
        return False

def main():
    """Run all validation tests"""
    print("=" * 60)
    print("DarkstarAIC Multi-Server Feature Validation")
    print("=" * 60)
    
    tests = [
        test_imports,
        test_module_structure,
        test_documentation,
        test_environment_handling,
        test_backward_compatibility,
    ]
    
    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as e:
            print(f"\n✗ Test {test.__name__} failed with exception: {e}")
            results.append(False)
    
    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("✓ All validation tests passed!")
        return 0
    else:
        print("✗ Some tests failed")
        return 1

if __name__ == '__main__':
    sys.exit(main())
