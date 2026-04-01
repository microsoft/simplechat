#!/usr/bin/env python3
"""
Enhanced Azure Document Intelligence Debugging Test

This test provides detailed debugging information about the Azure Document Intelligence
client and API compatibility to help diagnose the 'document' parameter error.
"""

import sys
import os

# Add the parent directory to the path so we can import from the main app
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

def test_azure_di_client_diagnostics():
    """Test Azure DI client configuration and available methods."""
    print("🔍 Running Azure Document Intelligence Client Diagnostics...")
    
    try:
        from config import CLIENTS, AZURE_ENVIRONMENT
        
        if 'document_intelligence_client' not in CLIENTS:
            print("❌ Document Intelligence client not configured")
            return False
        
        client = CLIENTS['document_intelligence_client']
        
        print(f"✅ Client found: {type(client)}")
        print(f"✅ Azure Environment: {AZURE_ENVIRONMENT}")
        
        # Check library versions
        try:
            import azure.ai.documentintelligence
            print(f"✅ DocumentIntelligence library version: {azure.ai.documentintelligence.__version__}")
        except Exception as e:
            print(f"⚠️  Could not get DocumentIntelligence version: {e}")
        
        try:
            import azure.ai.formrecognizer
            print(f"✅ FormRecognizer library version: {azure.ai.formrecognizer.__version__}")
        except Exception as e:
            print(f"⚠️  Could not get FormRecognizer version: {e}")
        
        # Check available methods
        methods = [method for method in dir(client) if not method.startswith('_')]
        print(f"✅ Available client methods: {methods}")
        
        # Check specific methods we're interested in
        if hasattr(client, 'begin_analyze_document'):
            print("✅ begin_analyze_document method is available")
            
            # Try to inspect the method signature
            import inspect
            try:
                sig = inspect.signature(client.begin_analyze_document)
                print(f"✅ Method signature: {sig}")
            except Exception as e:
                print(f"⚠️  Could not inspect method signature: {e}")
        else:
            print("❌ begin_analyze_document method is NOT available")
        
        return True
        
    except Exception as e:
        print(f"❌ Diagnostics failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_create_temporary_pdf():
    """Create a small test PDF for testing."""
    print("🔍 Creating temporary test PDF...")
    
    try:
        import tempfile
        
        # Create a simple PDF content (just text-based)
        pdf_content = """%PDF-1.4
1 0 obj
<<
/Type /Catalog
/Pages 2 0 R
>>
endobj

2 0 obj
<<
/Type /Pages
/Kids [3 0 R]
/Count 1
>>
endobj

3 0 obj
<<
/Type /Page
/Parent 2 0 R
/MediaBox [0 0 612 792]
/Contents 4 0 R
>>
endobj

4 0 obj
<<
/Length 44
>>
stream
BT
/F1 12 Tf
72 720 Td
(Test PDF Document) Tj
ET
endstream
endobj

xref
0 5
0000000000 65535 f 
0000000015 00000 n 
0000000068 00000 n 
0000000125 00000 n 
0000000213 00000 n 
trailer
<<
/Size 5
/Root 1 0 R
>>
startxref
305
%%EOF"""
        
        # Create temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdf', delete=False) as temp_file:
            temp_file.write(pdf_content)
            temp_file_path = temp_file.name
        
        print(f"✅ Created test PDF: {temp_file_path}")
        return temp_file_path
        
    except Exception as e:
        print(f"❌ Failed to create test PDF: {e}")
        return None

def test_azure_di_api_call():
    """Test actual Azure DI API call with detailed error handling."""
    print("🔍 Testing Azure Document Intelligence API call...")
    
    try:
        from config import CLIENTS, AZURE_ENVIRONMENT
        from functions_content import extract_content_with_azure_di
        
        if 'document_intelligence_client' not in CLIENTS:
            print("❌ Document Intelligence client not configured - skipping API test")
            return True
        
        # Create a test PDF
        test_pdf_path = test_create_temporary_pdf()
        if not test_pdf_path:
            print("❌ Could not create test PDF")
            return False
        
        try:
            print("🔍 Calling extract_content_with_azure_di...")
            result = extract_content_with_azure_di(test_pdf_path)
            print(f"✅ API call succeeded! Result: {result}")
            return True
            
        except Exception as e:
            print(f"❌ API call failed: {e}")
            import traceback
            traceback.print_exc()
            return False
            
        finally:
            # Clean up test file
            try:
                os.unlink(test_pdf_path)
                print(f"✅ Cleaned up test file: {test_pdf_path}")
            except Exception as ex:
                pass
        
    except Exception as e:
        print(f"❌ Test setup failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    tests = [
        test_azure_di_client_diagnostics,
        test_azure_di_api_call
    ]
    results = []
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("🎉 All diagnostics passed!")
    else:
        print("💥 Some diagnostics failed. Check the output above for details.")
    
    sys.exit(0 if success else 1)
