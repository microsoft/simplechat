#!/usr/bin/env python3
"""
Test clean document detection logic
"""

print('🧪 Testing clean document detection logic...')

# Simulate the document info we expect
selected_doc_info = [
    {
        'display_name': 'United States Treasury - Financial Transactions Report',
        'title': 'Financial Transactions Report'
    },
    {
        'display_name': 'Informe Financiero - Compañía Ficticia Americana', 
        'title': 'Sunrise Innovations Inc'
    }
]

clean_document_indicators = [
    'United States Treasury',
    'Financial Transactions Report', 
    'Compañía Ficticia Americana',
    'Sunrise Innovations Inc',
    'Treasury Department',
    'Quarterly Financial Statement'
]

# Test the detection logic
is_clean_documents = False
for doc_info in selected_doc_info:
    doc_name = doc_info.get('display_name', '') + ' ' + doc_info.get('title', '')
    print(f'📄 Checking document: "{doc_name}"')
    
    for indicator in clean_document_indicators:
        if indicator.lower() in doc_name.lower():
            print(f'  ✅ Found indicator: "{indicator}" in document name')
            is_clean_documents = True
            break
    
    if is_clean_documents:
        break

print(f'\n🎯 Final result: is_clean_documents = {is_clean_documents}')
print(f'📊 Expected document_source: {"clean_documents" if is_clean_documents else "fraud_demo"}')