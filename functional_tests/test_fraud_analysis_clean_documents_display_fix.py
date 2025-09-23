#!/usr/bin/env python3
"""
Functional test for fraud analysis clean documents display fix.
Version: 0.229.100
Implemented in: 0.229.100

This test ensures that clean documents (United States Treasury and Spanish financial 
reports) are properly displayed in the Document Analysis section of the fraud analysis 
workflow, fixing the JavaScript syntax error and document loading issues.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_fraud_analysis_template_syntax():
    """Test that the fraud analysis template has valid JavaScript syntax."""
    print("🔍 Testing fraud analysis template syntax...")
    
    try:
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app', 'templates', 'workflow_bulk_fraud_analysis.html'
        )
        
        if not os.path.exists(template_path):
            print(f"❌ Template file not found: {template_path}")
            return False
        
        # Read the template file
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for common JavaScript syntax issues that were fixed
        issues_found = []
        
        # Check for duplicate mockDocuments declarations (should be fixed)
        mockDocuments_count = content.count('const mockDocuments = [];')
        if mockDocuments_count > 1:
            issues_found.append(f"Duplicate mockDocuments declarations found: {mockDocuments_count}")
        
        # Check for incomplete for loops
        incomplete_for_loops = content.count('for (let i = 1; i <=') - content.count('for (let i = 1; i <= {{ document_count }}; i++) {')
        if incomplete_for_loops > 0:
            issues_found.append(f"Incomplete for loop declarations found: {incomplete_for_loops}")
        
        # Check for proper try-catch structure
        try_count = content.count('try {')
        catch_count = content.count('} catch (')
        if try_count != catch_count:
            issues_found.append(f"Mismatched try-catch blocks: {try_count} try, {catch_count} catch")
        
        # Check for the improved document processing logic
        if 'console.log(\'🔍 Raw documents type:\', typeof actualDocuments);' not in content:
            issues_found.append("Missing enhanced debugging for document processing")
        
        if 'Array.isArray(actualDocuments)' not in content:
            issues_found.append("Missing Array.isArray check for document validation")
        
        if issues_found:
            print("❌ JavaScript syntax issues found:")
            for issue in issues_found:
                print(f"   • {issue}")
            return False
        
        print("✅ Fraud analysis template syntax validation passed!")
        return True
        
    except Exception as e:
        print(f"❌ Error during template validation: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_document_processing_logic():
    """Test the document processing logic improvements."""
    print("🔍 Testing document processing logic...")
    
    try:
        # This test validates the logical flow without running the actual template
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app', 'templates', 'workflow_bulk_fraud_analysis.html'
        )
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for improved document property handling
        required_logic = [
            'doc.title || doc.display_name || doc.file_name || doc.filename',
            'doc.content || doc.text || \'Document content not available\'',
            'typeof docSize === \'string\' ? parseInt(docSize)',
            'rawDocKeys: Object.keys(doc)',
            'console.log(\'📄 Document details:\', selectedDocuments);'
        ]
        
        missing_logic = []
        for logic in required_logic:
            if logic not in content:
                missing_logic.append(logic)
        
        if missing_logic:
            print("❌ Missing improved document processing logic:")
            for logic in missing_logic:
                print(f"   • {logic}")
            return False
        
        print("✅ Document processing logic validation passed!")
        return True
        
    except Exception as e:
        print(f"❌ Error during logic validation: {e}")
        return False

def test_clean_documents_support():
    """Test that clean documents are properly supported."""
    print("🔍 Testing clean documents support...")
    
    try:
        # Check the Flask route for clean document handling
        route_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'single_app', 'route_frontend_workflow.py'
        )
        
        if not os.path.exists(route_path):
            print(f"❌ Route file not found: {route_path}")
            return False
        
        with open(route_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for clean document indicators
        clean_indicators = [
            'United States Treasury',
            'Compañía Ficticia Americana',
            'document_source = "clean_documents"',
            'is_clean_documents = True'
        ]
        
        missing_indicators = []
        for indicator in clean_indicators:
            if indicator not in content:
                missing_indicators.append(indicator)
        
        if missing_indicators:
            print("❌ Missing clean document support:")
            for indicator in missing_indicators:
                print(f"   • {indicator}")
            return False
        
        print("✅ Clean documents support validation passed!")
        return True
        
    except Exception as e:
        print(f"❌ Error during clean documents validation: {e}")
        return False

if __name__ == "__main__":
    tests = [
        test_fraud_analysis_template_syntax,
        test_document_processing_logic,
        test_clean_documents_support
    ]
    results = []
    
    print("🧪 Running fraud analysis clean documents display fix tests...\n")
    
    for test in tests:
        print(f"🧪 Running {test.__name__}...")
        results.append(test())
        print()
    
    success = all(results)
    print(f"📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("🎉 All fraud analysis clean documents display fix tests passed!")
        print("✅ The JavaScript syntax error has been fixed")
        print("✅ Document processing logic has been improved") 
        print("✅ Clean documents should now display properly")
    else:
        print("❌ Some tests failed - fraud analysis display may have issues")
    
    sys.exit(0 if success else 1)
