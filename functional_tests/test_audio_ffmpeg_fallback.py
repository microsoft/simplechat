#!/usr/bin/env python3
# test_audio_ffmpeg_fallback.py
"""
Functional test for audio upload fallback when ffmpeg is unavailable.
Version: 0.250.011
Implemented in: 0.250.009
Updated in: 0.250.011

This test ensures supported audio uploads can fall back to Azure Speech fast
transcription when local ffmpeg is missing, and that container/admin runtime
support for broad audio transcoding is wired consistently.
"""

import ast
import os
import re
import shutil
import subprocess
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINGLE_APP_ROOT = os.path.join(ROOT_DIR, 'application', 'single_app')
FUNCTIONS_DOCUMENTS_FILE = os.path.join(SINGLE_APP_ROOT, 'functions_documents.py')
CONFIG_FILE = os.path.join(SINGLE_APP_ROOT, 'config.py')
DOCKERFILE = os.path.join(SINGLE_APP_ROOT, 'Dockerfile')
ADMIN_SETTINGS_ROUTE_FILE = os.path.join(SINGLE_APP_ROOT, 'route_frontend_admin_settings.py')
ADMIN_SETTINGS_TEMPLATE = os.path.join(SINGLE_APP_ROOT, 'templates', 'admin_settings.html')
DEPLOYER_AZURE_YAML = os.path.join(ROOT_DIR, 'deployers', 'azure.yaml')
DEPLOYER_VERSION_FILE = os.path.join(ROOT_DIR, 'deployers', 'version.txt')


def read_file(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def parse_functions_documents():
    source = read_file(FUNCTIONS_DOCUMENTS_FILE)
    return ast.parse(source, filename=FUNCTIONS_DOCUMENTS_FILE), source


def get_function(module_ast, function_name):
    functions = [
        node for node in module_ast.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    ]
    assert functions, f'Missing function: {function_name}'
    return functions[-1]


def test_missing_ffmpeg_detection():
    """Verify the fallback detector recognizes the upload failure signature."""
    print('Testing missing ffmpeg detection...')

    module_ast, _ = parse_functions_documents()
    detector = get_function(module_ast, '_is_missing_ffmpeg_error')
    isolated_module = ast.Module(body=[detector], type_ignores=[])
    namespace = {}
    exec(compile(isolated_module, FUNCTIONS_DOCUMENTS_FILE, 'exec'), namespace)
    is_missing_ffmpeg_error = namespace['_is_missing_ffmpeg_error']

    assert is_missing_ffmpeg_error(
        RuntimeError("Segmentation failed: [Errno 2] No such file or directory: 'ffmpeg'")
    )
    assert is_missing_ffmpeg_error(
        RuntimeError("Segmentation failed: ffmpeg: The system cannot find the file specified")
    )
    assert not is_missing_ffmpeg_error(
        RuntimeError('Segmentation failed: invalid data found when processing input')
    )
    assert not is_missing_ffmpeg_error(RuntimeError('Azure Speech request failed'))

    print('Missing ffmpeg detection passed')
    return True


def test_public_cloud_fast_transcription_fallback():
    """Verify public clouds can bypass local segmentation for source audio."""
    print('Testing public cloud fast transcription fallback...')

    module_ast, source = parse_functions_documents()
    process_audio = get_function(module_ast, 'process_audio_document')
    process_source = ast.get_source_segment(source, process_audio)

    required_snippets = [
        'except RuntimeError as split_error:',
        'AZURE_ENVIRONMENT not in ("usgovernment", "custom")',
        '_is_missing_ffmpeg_error(split_error)',
        'use_source_audio_for_fast_api = True',
        'Transcribing audio with Azure Speech',
        '_transcribe_audio_with_fast_api(',
        '_get_content_type(original_filename or temp_file_path)',
    ]
    missing_snippets = [snippet for snippet in required_snippets if snippet not in process_source]
    assert not missing_snippets, f'Missing fallback snippets: {missing_snippets}'

    print('Public cloud fast transcription fallback passed')
    return True


def test_audio_runtime_capabilities_are_reported():
    """Verify audio runtime capability reporting has the admin UI contract."""
    print('Testing audio runtime capability reporting...')

    module_ast, _ = parse_functions_documents()
    capability_function = get_function(module_ast, 'get_audio_runtime_capabilities')
    isolated_module = ast.Module(body=[capability_function], type_ignores=[])
    namespace = {
        '_AUDIO_RUNTIME_CAPABILITIES_CACHE': None,
        'AUDIO_EXTENSIONS': {'mp3', 'wav', 'ogg', 'aac', 'flac', 'm4a', 'opus', 'wma', '3ga'},
        'AUDIO_FAST_TRANSCRIPTION_SOURCE_EXTENSIONS': {'aac', 'flac', 'm4a', 'mp3', 'ogg', 'wav'},
        'shutil': shutil,
        'subprocess': subprocess,
    }
    exec(compile(isolated_module, FUNCTIONS_DOCUMENTS_FILE, 'exec'), namespace)
    capabilities = namespace['get_audio_runtime_capabilities'](force_refresh=True)

    assert isinstance(capabilities['ffmpeg_available'], bool)
    assert isinstance(capabilities['ffprobe_available'], bool)
    assert isinstance(capabilities['broad_transcoding_available'], bool)
    assert '.m4a' in capabilities['supported_extensions']
    assert '.opus' in capabilities['supported_extensions']
    assert '.m4a' in capabilities['direct_transcription_extensions']
    assert 'ffmpeg' in capabilities['recommended_container_packages']
    assert isinstance(capabilities['message'], str)

    print('Audio runtime capability reporting passed')
    return True


def test_common_audio_extensions_and_content_types_are_registered():
    """Verify common audio containers are accepted and mapped for source fallback."""
    print('Testing common audio extension registration...')

    config_source = read_file(CONFIG_FILE)
    functions_source = read_file(FUNCTIONS_DOCUMENTS_FILE)
    expected_extensions = [
        '3ga', 'aac', 'ac3', 'aif', 'aiff', 'amr', 'ape', 'au', 'caf',
        'dts', 'f4a', 'flac', 'm4a', 'm4b', 'm4r', 'mka', 'mp2', 'mp3',
        'mpa', 'oga', 'ogg', 'opus', 'spx', 'wav', 'weba', 'wma', 'wv'
    ]

    for extension in expected_extensions:
        assert f"'{extension}'" in config_source, f'Missing AUDIO_EXTENSIONS entry: {extension}'
        assert f"'.{extension}'" in functions_source, f'Missing content type mapping for .{extension}'

    assert "map='0:a:0'" in functions_source, 'FFmpeg splitting should map the first audio stream only'
    assert "ac='1'" in functions_source, 'FFmpeg splitting should emit mono audio for Speech'

    print('Common audio extension registration passed')
    return True


def test_container_and_deployer_install_ffmpeg_by_default():
    """Verify the container and deployer build paths package FFmpeg by default."""
    print('Testing FFmpeg container packaging wiring...')

    docker_source = read_file(DOCKERFILE)
    deployer_source = read_file(DEPLOYER_AZURE_YAML)
    deployer_version = read_file(DEPLOYER_VERSION_FILE).strip()

    docker_snippets = [
        'ARG INSTALL_AUDIO_FFMPEG=true',
        'ARG INSTALL_AUDIO_FFMPEG',
        'ffmpeg_bin.init()',
        "shutil.copy2(ffmpeg_bin.FFMPEG_PATH, target_dir / 'ffmpeg')",
        "shutil.copy2(ffmpeg_bin.FFPROBE_PATH, target_dir / 'ffprobe')",
        'COPY --from=builder /audio-runtime/ /',
        'PATH="/usr/bin:/home/nonroot/.local/bin:$PATH"',
    ]
    missing_docker_snippets = [snippet for snippet in docker_snippets if snippet not in docker_source]
    assert not missing_docker_snippets, f'Missing Dockerfile snippets: {missing_docker_snippets}'

    deployer_snippets = [
        'SIMPLECHAT_INSTALL_FFMPEG',
        'INSTALL_AUDIO_FFMPEG=${install_audio_ffmpeg}',
        'INSTALL_AUDIO_FFMPEG=$installAudioFfmpeg',
        'Audio FFmpeg runtime install',
    ]
    missing_deployer_snippets = [snippet for snippet in deployer_snippets if snippet not in deployer_source]
    assert not missing_deployer_snippets, f'Missing deployer snippets: {missing_deployer_snippets}'
    assert deployer_version == '1.0.21', 'Expected deployers/version.txt 1.0.21'

    print('FFmpeg container packaging wiring passed')
    return True


def test_admin_audio_runtime_status_is_rendered():
    """Verify Admin Settings receives and renders audio runtime support details."""
    print('Testing admin audio runtime status rendering...')

    route_source = read_file(ADMIN_SETTINGS_ROUTE_FILE)
    template_source = read_file(ADMIN_SETTINGS_TEMPLATE)

    required_route_snippets = [
        'audio_runtime_capabilities = get_audio_runtime_capabilities()',
        'audio_runtime_capabilities=audio_runtime_capabilities',
    ]
    missing_route_snippets = [snippet for snippet in required_route_snippets if snippet not in route_source]
    assert not missing_route_snippets, f'Missing admin route snippets: {missing_route_snippets}'

    required_template_snippets = [
        'audio_runtime_status',
        'audio_supported_extensions',
        'Supported audio upload extensions:',
        'Container builds can include FFmpeg for broader codec support.',
    ]
    missing_template_snippets = [snippet for snippet in required_template_snippets if snippet not in template_source]
    assert not missing_template_snippets, f'Missing admin template snippets: {missing_template_snippets}'

    print('Admin audio runtime status rendering passed')
    return True


def test_fast_api_uses_supplied_content_type():
    """Verify the fast-transcription helper does not force source audio to WAV."""
    print('Testing fast API content type handling...')

    module_ast, source = parse_functions_documents()
    helper = get_function(module_ast, '_transcribe_audio_with_fast_api')
    helper_source = ast.get_source_segment(source, helper)

    assert "'audio': (upload_filename, audio_f, content_type)" in helper_source, (
        'Fast transcription helper must preserve the caller-provided content type'
    )
    assert "'audio/wav'" not in helper_source, (
        'Fast transcription helper should not force every source upload to WAV'
    )

    print('Fast API content type handling passed')
    return True


def test_config_version_bumped_for_audio_fallback_fix():
    """Verify config.py version was bumped for this fix."""
    print('Testing config version bump...')

    config_source = read_file(CONFIG_FILE)
    version_match = re.search(r'VERSION = "([0-9.]+)"', config_source)
    assert version_match, 'Could not find VERSION in config.py'
    assert version_match.group(1) == '0.250.011', 'Expected config.py version 0.250.011'

    print('Config version bump passed')
    return True


if __name__ == '__main__':
    tests = [
        test_missing_ffmpeg_detection,
        test_public_cloud_fast_transcription_fallback,
        test_audio_runtime_capabilities_are_reported,
        test_common_audio_extensions_and_content_types_are_registered,
        test_container_and_deployer_install_ffmpeg_by_default,
        test_admin_audio_runtime_status_is_rendered,
        test_fast_api_uses_supplied_content_type,
        test_config_version_bumped_for_audio_fallback_fix,
    ]

    results = []
    for test in tests:
        print(f'Running {test.__name__}...')
        try:
            results.append(test())
        except Exception as test_error:
            print(f'Test failed: {test_error}')
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f'Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)