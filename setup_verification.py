#!/usr/bin/env python3
"""
XFA to Markdown Setup Verification Script
For AI coding agents to verify environment setup
"""

import sys
import os
import subprocess
from pathlib import Path

def check_python_version():
    """Check Python version compatibility"""
    version = sys.version_info
    print(f"🐍 Python Version: {version.major}.{version.minor}.{version.micro}")
    
    if version.major >= 3 and version.minor >= 7:
        print("✅ Python version compatible")
        return True
    else:
        print("❌ Python 3.7+ required")
        return False

def check_dependencies():
    """Check required dependencies"""
    dependencies = ['pikepdf']
    all_good = True
    
    for dep in dependencies:
        try:
            __import__(dep)
            # Get version if available
            try:
                module = __import__(dep)
                version = getattr(module, '__version__', 'unknown')
                print(f"✅ {dep}: {version}")
            except:
                print(f"✅ {dep}: installed")
        except ImportError:
            print(f"❌ {dep}: not installed")
            print(f"   Install with: python3 -m pip install {dep}")
            all_good = False
    
    return all_good

def check_script_exists():
    """Check if the main script exists"""
    script_path = Path("xfa_to_markdown.py")
    
    if script_path.exists():
        print(f"✅ Script found: {script_path.absolute()}")
        
        # Check if executable
        if os.access(script_path, os.X_OK):
            print("✅ Script is executable")
        else:
            print("⚠️  Script not executable, fixing...")
            os.chmod(script_path, 0o755)
            print("✅ Script made executable")
        
        return True
    else:
        print(f"❌ Script not found: {script_path.absolute()}")
        return False

def test_script_help():
    """Test script help command"""
    try:
        result = subprocess.run(
            ['python3', 'xfa_to_markdown.py', '--help'],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            print("✅ Script help command works")
            return True
        else:
            print(f"❌ Script help failed: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        print("❌ Script help command timed out")
        return False
    except Exception as e:
        print(f"❌ Error testing script: {e}")
        return False

def check_sample_pdf():
    """Check if sample PDF exists for testing"""
    sample_pdfs = [
        "imm5257e (1).pdf",
        "*.pdf"
    ]
    
    found_pdfs = []
    for pattern in sample_pdfs:
        if '*' in pattern:
            # Find any PDF files
            pdf_files = list(Path('.').glob('*.pdf'))
            found_pdfs.extend(pdf_files)
        else:
            pdf_path = Path(pattern)
            if pdf_path.exists():
                found_pdfs.append(pdf_path)
    
    if found_pdfs:
        print(f"✅ Found {len(found_pdfs)} PDF file(s) for testing:")
        for pdf in found_pdfs[:3]:  # Show first 3
            print(f"   - {pdf}")
        if len(found_pdfs) > 3:
            print(f"   ... and {len(found_pdfs) - 3} more")
        return True
    else:
        print("⚠️  No PDF files found for testing")
        print("   You can test with any XFA PDF file")
        return False

def run_verification():
    """Run complete verification"""
    print("🔍 XFA to Markdown Setup Verification")
    print("=" * 50)
    
    checks = [
        ("Python Version", check_python_version),
        ("Dependencies", check_dependencies),
        ("Script Exists", check_script_exists),
        ("Script Help", test_script_help),
        ("Sample PDFs", check_sample_pdf)
    ]
    
    results = {}
    for name, check_func in checks:
        print(f"\n📋 Checking: {name}")
        results[name] = check_func()
    
    print("\n" + "=" * 50)
    print("📊 VERIFICATION SUMMARY")
    print("=" * 50)
    
    critical_checks = ["Python Version", "Dependencies", "Script Exists", "Script Help"]
    critical_passed = all(results[check] for check in critical_checks if check in results)
    
    for name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        critical = " (CRITICAL)" if name in critical_checks else ""
        print(f"{status} {name}{critical}")
    
    print("\n" + "=" * 50)
    
    if critical_passed:
        print("🎉 SETUP COMPLETE - Ready to process XFA PDFs!")
        print("\n📝 Quick test command:")
        print("   python3 xfa_to_markdown.py your_file.pdf")
        return True
    else:
        print("❌ SETUP INCOMPLETE - Fix critical issues above")
        print("\n🔧 Common fixes:")
        print("   pip install pikepdf")
        print("   chmod +x xfa_to_markdown.py")
        return False

if __name__ == "__main__":
    success = run_verification()
    sys.exit(0 if success else 1)
