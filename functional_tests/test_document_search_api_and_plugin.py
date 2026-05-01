#!/usr/bin/env python3
# test_document_search_api_and_plugin.py
"""
Functional test for document search API and core Semantic Kernel plugin.
Version: 0.241.007
Implemented in: 0.241.007

This test ensures that the shared search service, backend API, and always-loaded
Semantic Kernel document search plugin expose the expected contract for hybrid
search, ordered chunk retrieval, and hierarchical summarization.
"""

import ast
import os
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, 'application', 'single_app')


def read_source(*relative_parts):
    file_path = os.path.join(REPO_ROOT, *relative_parts)
    with open(file_path, 'r', encoding='utf-8') as source_file:
        return source_file.read()


def parse_module(*relative_parts):
    source = read_source(*relative_parts)
    return source, ast.parse(source)


def get_function_names(module_ast):
    return {
        node.name
        for node in module_ast.body
        if isinstance(node, ast.FunctionDef)
    }


def get_class_method_names(module_ast, class_name):
    for node in module_ast.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                child.name
                for child in node.body
                if isinstance(child, ast.FunctionDef)
            }
    return set()


def test_functions_search_contract():
    print('🔍 Validating shared search helper contract...')
    source, module_ast = parse_module('application', 'single_app', 'functions_search.py')
    function_names = get_function_names(module_ast)

    required_functions = {
        'normalize_search_top_n',
        'normalize_search_scope',
        'normalize_search_id_list',
        'extract_search_results',
    }
    missing_functions = sorted(required_functions - function_names)
    if missing_functions:
        print(f'❌ Missing search helper functions: {missing_functions}')
        return False

    required_snippets = [
        'SEARCH_DEFAULT_TOP_N = 12',
        'SEARCH_MAX_TOP_N = 500',
        '"document_id": r.get("document_id")',
        'select=get_search_select_fields("personal")',
        'select=get_search_select_fields("group")',
        'select=get_search_select_fields("public")',
    ]
    missing_snippets = [snippet for snippet in required_snippets if snippet not in source]
    if missing_snippets:
        print(f'❌ Missing search helper snippets: {missing_snippets}')
        return False

    print('✅ Shared search helpers expose normalized top-n, scope, and document ids')
    return True


def test_search_service_contract():
    print('\n🔍 Validating shared search service contract...')
    source, module_ast = parse_module('application', 'single_app', 'functions_search_service.py')
    function_names = get_function_names(module_ast)

    required_functions = {
        'resolve_document_context',
        'build_search_request',
        'search_documents',
        'build_document_chunk_windows',
        'get_document_chunks_payload',
        'summarize_document_content',
    }
    missing_functions = sorted(required_functions - function_names)
    if missing_functions:
        print(f'❌ Missing search service functions: {missing_functions}')
        return False

    if 'SUMMARY_DEFAULT_WINDOW_SUMMARY_TARGET = "2 pages"' not in source:
        print('❌ Missing hierarchical summary window target default')
        return False

    if 'SUMMARY_DEFAULT_FINAL_TARGET = "2 pages"' not in source:
        print('❌ Missing hierarchical summary final target default')
        return False

    print('✅ Shared search service exposes retrieval and summarization entry points')
    return True


def test_backend_search_routes():
    print('\n🔍 Validating backend search route contract...')
    source, _ = parse_module('application', 'single_app', 'route_backend_search.py')

    required_routes = [
        "/api/search/documents",
        "/api/search/document-chunks",
        "/api/search/document-summary",
    ]
    missing_routes = [route for route in required_routes if route not in source]
    if missing_routes:
        print(f'❌ Missing backend search routes: {missing_routes}')
        return False

    required_decorators = [
        '@swagger_route(security=get_auth_security())',
        '@login_required',
        '@user_required',
    ]
    missing_decorators = [decorator for decorator in required_decorators if decorator not in source]
    if missing_decorators:
        print(f'❌ Missing backend route decorators: {missing_decorators}')
        return False

    print('✅ Backend search routes expose authenticated search, chunk retrieval, and summary endpoints')
    return True


def test_document_search_plugin_contract():
    print('\n🔍 Validating document search plugin contract...')
    source, module_ast = parse_module('application', 'single_app', 'semantic_kernel_plugins', 'document_search_plugin.py')
    method_names = get_class_method_names(module_ast, 'DocumentSearchPlugin')

    required_methods = {
        'search_documents',
        'retrieve_document_chunks',
        'summarize_document',
    }
    missing_methods = sorted(required_methods - method_names)
    if missing_methods:
        print(f'❌ Missing plugin methods: {missing_methods}')
        return False

    required_kernel_names = [
        "name='search_documents'",
        "name='retrieve_document_chunks'",
        "name='summarize_document'",
    ]
    missing_kernel_names = [value for value in required_kernel_names if value not in source]
    if missing_kernel_names:
        print(f'❌ Missing kernel function names: {missing_kernel_names}')
        return False

    print('✅ Document search plugin exposes the expected kernel functions')
    return True


def test_loader_and_app_registration():
    print('\n🔍 Validating loader and app registration...')
    loader_source = read_source('application', 'single_app', 'semantic_kernel_loader.py')
    app_source = read_source('application', 'single_app', 'app.py')

    if 'from semantic_kernel_plugins.document_search_plugin import DocumentSearchPlugin' not in loader_source:
        print('❌ Semantic Kernel loader does not import DocumentSearchPlugin')
        return False

    loader_registration_count = loader_source.count('load_document_search_plugin(kernel)')
    if loader_registration_count < 2:
        print(f'❌ Expected document search plugin to be loaded in both SK paths, found {loader_registration_count}')
        return False

    if 'from route_backend_search import *' not in app_source:
        print('❌ Flask app does not import route_backend_search')
        return False

    if 'register_route_backend_search(app)' not in app_source:
        print('❌ Flask app does not register route_backend_search')
        return False

    print('✅ Loader and app register the core plugin and backend routes')
    return True


def main():
    print('🧪 Running Document Search API And Plugin Tests')
    print('=' * 64)

    tests = [
        test_functions_search_contract,
        test_search_service_contract,
        test_backend_search_routes,
        test_document_search_plugin_contract,
        test_loader_and_app_registration,
    ]

    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as e:
            print(f'❌ {test.__name__} raised an exception: {e}')
            results.append(False)

    passed_count = sum(results)
    total_count = len(results)

    print('\n' + '=' * 64)
    print(f'📊 Results: {passed_count}/{total_count} tests passed')

    return passed_count == total_count


if __name__ == '__main__':
    if APP_ROOT not in sys.path:
        sys.path.insert(0, APP_ROOT)
    success = main()
    sys.exit(0 if success else 1)