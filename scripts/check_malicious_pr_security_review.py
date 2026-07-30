# check_malicious_pr_security_review.py

"""Run static malicious-change review checks for changed files."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
DIFF_HUNK_RE = re.compile(r'^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@')
HIDDEN_UNICODE_RE = re.compile('[\u202a-\u202e\u2066-\u2069\u200b\u200c\u200d\ufeff]')
URL_RE = re.compile(r'https?://[^\s\'"<>)]+', re.IGNORECASE)
PYTHON_REQUIREMENT_RE = re.compile(
    r'^(?P<name>[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?)==(?P<version>[A-Za-z0-9][A-Za-z0-9_.!+\-]*)'
    r'(?:\s*;\s*.+)?$'
)
NPM_EXACT_VERSION_RE = re.compile(r'^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$')
GITHUB_ACTION_REF_RE = re.compile(r'uses:\s*([^\s#]+@([^\s#]+))')
DOCKER_FROM_RE = re.compile(r'^\s*FROM\s+(?P<image>[^\s]+)', re.IGNORECASE)

REVIEW_RULES = [
    (
        'Important',
        'Needs investigation',
        'external connection or remote asset marker',
        re.compile(
            r'https?://|webhook|telemetry|analytics|beacon|sendBeacon|fetch\(|XMLHttpRequest|WebSocket|EventSource|'
            r'requests\.|httpx\.|aiohttp|urllib|socket\.|smtplib|ftplib|paramiko|scp|Invoke-WebRequest|'
            r'Invoke-RestMethod|curl|wget|nslookup|Resolve-DnsName|cdn\.|unpkg|jsdelivr|cdnjs|esm\.sh|skypack',
            re.IGNORECASE,
        ),
        'Review whether changed code can send prompts, files, credentials, cookies, settings, logs, or user data to a new sink.',
        'network, browser-load, deploy, or CI path',
    ),
    (
        'Important',
        'Needs investigation',
        'secret or sensitive data source marker',
        re.compile(
            r'api[_-]?key|secret|password|passwd|pwd|token|bearer|credential|connection[_ -]?string|client[_-]?secret|'
            r'private[_-]?key|account[_-]?key|sas[_-]?token|Authorization|Cookie|get_settings\(|os\.environ|process\.env|'
            r'localStorage|sessionStorage|document\.cookie|id_rsa|\.env|MSAL|OPENAI|COSMOS|SEARCH|BLOB|STORAGE|KEYVAULT|GRAPH',
            re.IGNORECASE,
        ),
        'Pair this source with any nearby network, logging, serialization, or process execution sink before approving.',
        'request, browser, import, deploy, or CI path',
    ),
    (
        'Moderate',
        'Needs investigation',
        'obfuscation, dynamic loading, or hidden payload marker',
        re.compile(
            r'base64|b64decode|atob\(|fromCharCode|charCodeAt|unescape\(|decodeURIComponent|zlib|gzip|brotli|'
            r'marshal|pickle|loads\(|exec\(|eval\(|compile\(|new Function|Function\(|importlib|__import__|getattr\(|'
            r'setattr\(|globals\(\)|locals\(\)|Reflection|Add-Type|EncodedCommand|FromBase64String|IEX|Invoke-Expression|'
            r'Start-Process|hidden|homoglyph|bidi|unicode',
            re.IGNORECASE,
        ),
        'Confirm the changed code is not hiding behavior, decoding payloads, or bypassing normal review.',
        'import, request, browser, deploy, or CI path',
    ),
    (
        'Important',
        'Needs investigation',
        'dynamic execution, persistence, or system access marker',
        re.compile(
            r'subprocess|os\.system|popen|shell=True|pty|spawn|execFile|child_process|ProcessStartInfo|Start-Process|'
            r'New-Service|schtasks|crontab|systemctl|chmod|chown|icacls|reg add|Set-ItemProperty|pip install|npm install|'
            r'postinstall|preinstall|setup\.py|pyproject\.toml|entry_points|ctypes|cffi|ffi|DllImport|LoadLibrary|unsafe',
            re.IGNORECASE,
        ),
        'Do not execute changed lifecycle scripts or installers while this finding is unresolved.',
        'install, import, build, deploy, CI, or request path',
    ),
    (
        'Important',
        'Needs investigation',
        'security control, sanitization, or audit marker',
        re.compile(
            r'login_required|admin_required|user_required|swagger_route|get_auth_security|csrf|Content-Security-Policy|'
            r'sanitize_settings_for_user|escapeHtml|DOMPurify|innerHTML|outerHTML|insertAdjacentHTML|eval\(|debug\s*=\s*True|'
            r'verify\s*=\s*False|ssl|cert|validate|allowlist|denylist|permission|role|policy|redact|mask|log_event|audit|'
            r'telemetry|traceback|try:|except Exception|pass|skip|xfail|disable|noqa|type:\s*ignore|pragma',
            re.IGNORECASE,
        ),
        'Confirm the change does not weaken auth, CSRF, CSP, XSS defenses, settings sanitization, redaction, audit logging, or tests.',
        'request, browser, test, or CI path',
    ),
    (
        'Important',
        'Needs investigation',
        'AI, plugin, agent, or workspace boundary marker',
        re.compile(
            r'kernel_function|OpenAPI|plugin|agent|tool|prompt|instructions|chat_history|conversation|citation|embedding|'
            r'public_workspace|group_workspace|workspace_id|model_endpoint|azure_openai|semantic_kernel',
            re.IGNORECASE,
        ),
        'Check whether prompts, chat history, uploaded documents, embeddings, citations, settings, or identity can cross a new boundary.',
        'agent, plugin, request, search, or model path',
    ),
]

RISK_AREAS = {
    'application runtime': ('application/single_app/', 'application/external_apps/', 'application/teams_app/'),
    'browser runtime': ('.html', '.js', '.css', '.wasm', '.map', '.woff', '.woff2'),
    'dependency manifest': (
        'requirements',
        'package.json',
        'package-lock.json',
        'npm-shrinkwrap.json',
        'pnpm-lock.yaml',
        'yarn.lock',
        'pyproject.toml',
        'poetry.lock',
        'Pipfile',
        'Pipfile.lock',
        'Dockerfile',
    ),
    'infrastructure and deployment': ('deployers/', '.github/workflows/', 'Dockerfile', '.bicep', '.tf', '.ps1', 'azure.yaml'),
    'tests and validation': ('functional_tests/', 'ui_tests/', 'scripts/check_', 'pytest.ini'),
    'documentation and prompts': ('docs/', '.github/prompts/', '.github/instructions/'),
}


@dataclass(frozen=True)
class Finding:
    """A static review finding."""

    severity: str
    verdict: str
    file_path: str
    line: int
    message: str
    evidence: str
    reachability: str
    recommendation: str


@dataclass(frozen=True)
class DependencyRelease:
    """A dependency version selected for optional release-age verification."""

    ecosystem: str
    package_name: str
    version: str
    file_path: str
    line: int


def get_relative_path(file_path: Path) -> str:
    """Return a repository-relative path when possible."""
    try:
        return file_path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return file_path.as_posix()


def run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a git command from the repository root."""
    return subprocess.run(
        ['git', *args],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
    )


def get_changed_files(base_sha: str | None, head_sha: str | None) -> list[Path]:
    """Return changed paths from git."""
    if base_sha and head_sha:
        diff_args = ['diff', '--name-only', '--diff-filter=ACMRT', base_sha, head_sha]
    else:
        diff_args = ['diff', '--name-only', '--diff-filter=ACMRT', 'HEAD']

    result = run_git(diff_args)
    if result.returncode not in {0, 1}:
        raise RuntimeError(result.stderr.strip() or 'Unable to collect changed files from git')

    return [REPO_ROOT / path for path in result.stdout.splitlines() if path.strip()]


def normalize_paths(raw_paths: list[str]) -> list[Path]:
    """Resolve explicit CLI paths relative to the repository root."""
    paths: list[Path] = []
    for raw_path in raw_paths:
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = REPO_ROOT / candidate
        paths.append(candidate.resolve())
    return paths


def get_changed_lines(file_path: Path, base_sha: str | None, head_sha: str | None) -> set[int] | None:
    """Return added-line numbers for a file between revisions, or None for full-file mode."""
    if not base_sha or not head_sha:
        return None

    relative_path = get_relative_path(file_path)
    result = run_git(['diff', '--unified=0', base_sha, head_sha, '--', relative_path])
    if result.returncode not in {0, 1}:
        return None

    changed_lines: set[int] = set()
    for line in result.stdout.splitlines():
        match = DIFF_HUNK_RE.match(line)
        if not match:
            continue
        start_line = int(match.group('start'))
        line_count = int(match.group('count') or '1')
        if line_count > 0:
            changed_lines.update(range(start_line, start_line + line_count))

    return changed_lines


def is_text_file(file_path: Path) -> bool:
    """Return True when a file can be read as UTF-8-ish text."""
    try:
        sample = file_path.read_bytes()[:4096]
    except OSError:
        return False
    return b'\x00' not in sample


def read_text(file_path: Path) -> str | None:
    """Read a text file with replacement for invalid byte sequences."""
    if not file_path.exists() or not file_path.is_file() or not is_text_file(file_path):
        return None
    return file_path.read_text(encoding='utf-8', errors='replace')


def line_is_changed(line_number: int, changed_lines: set[int] | None, full_file: bool) -> bool:
    """Return True when a line should be inspected."""
    return full_file or changed_lines is None or line_number in changed_lines


def add_finding(
    findings: list[Finding],
    severity: str,
    verdict: str,
    file_path: Path,
    line: int,
    message: str,
    evidence: str,
    reachability: str,
    recommendation: str,
) -> None:
    """Append a finding with normalized path and evidence."""
    findings.append(
        Finding(
            severity=severity,
            verdict=verdict,
            file_path=get_relative_path(file_path),
            line=line,
            message=message,
            evidence=evidence.strip()[:400],
            reachability=reachability,
            recommendation=recommendation,
        )
    )


def scan_text_patterns(
    file_path: Path,
    source_text: str,
    changed_lines: set[int] | None,
    full_file: bool,
    findings: list[Finding],
) -> set[str]:
    """Scan one text file for suspicious static review markers."""
    discovered_urls: set[str] = set()
    for line_number, line in enumerate(source_text.splitlines(), start=1):
        if not line_is_changed(line_number, changed_lines, full_file):
            continue

        for url_match in URL_RE.finditer(line):
            discovered_urls.add(url_match.group(0).rstrip('.,'))

        if HIDDEN_UNICODE_RE.search(line):
            add_finding(
                findings,
                'Critical',
                'Blocker',
                file_path,
                line_number,
                'Hidden Unicode control character found in changed content.',
                line,
                'review-time and runtime parsing path',
                'Remove the hidden character or replace the line with plain visible text before approval.',
            )

        for severity, verdict, label, pattern, recommendation, reachability in REVIEW_RULES:
            if pattern.search(line):
                add_finding(
                    findings,
                    severity,
                    verdict,
                    file_path,
                    line_number,
                    f'Changed line contains {label}.',
                    line,
                    reachability,
                    recommendation,
                )

    return discovered_urls


def inspect_binary_file(file_path: Path, findings: list[Finding]) -> None:
    """Add a review finding for opaque changed binary content."""
    if not file_path.exists() or file_path.is_dir():
        return
    add_finding(
        findings,
        'Moderate',
        'Needs investigation',
        file_path,
        1,
        'Changed file is binary or opaque to text review.',
        file_path.name,
        'build, browser, documentation, or deploy artifact path',
        'Confirm the binary, generated asset, archive, certificate, model, or document is expected and inspectable.',
    )


def is_requirement_file(relative_path: str) -> bool:
    """Return True for Python requirements manifests."""
    name = Path(relative_path).name.lower()
    return name.startswith('requirements') and name.endswith('.txt')


def is_dependency_manifest(relative_path: str) -> bool:
    """Return True when a path should receive dependency-policy review."""
    path = relative_path.lower()
    name = Path(path).name
    return (
        is_requirement_file(relative_path)
        or name in {'package.json', 'package-lock.json', 'npm-shrinkwrap.json', 'pnpm-lock.yaml', 'yarn.lock'}
        or name in {'pyproject.toml', 'poetry.lock', 'pipfile', 'pipfile.lock', 'dockerfile'}
        or path.endswith('/dockerfile')
        or path.startswith('.github/workflows/')
    )


def inspect_requirements_file(
    file_path: Path,
    source_text: str,
    findings: list[Finding],
    releases: list[DependencyRelease],
) -> None:
    """Validate exact Python requirements pins and collect versions for release-age checks."""
    for line_number, raw_line in enumerate(source_text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith('#') or stripped.startswith('--hash='):
            continue

        if stripped.startswith(('-e ', '--extra-index-url', '--index-url', '--trusted-host')):
            add_finding(
                findings,
                'Critical',
                'Blocker',
                file_path,
                line_number,
                'Python requirement uses an editable install, custom index, or trusted-host override.',
                raw_line,
                'dependency resolution or install time',
                'Use reviewed public registry packages pinned with package==version, or document and approve an exception.',
            )
            continue

        if re.search(r'https?://|git\+|file:', stripped, re.IGNORECASE):
            add_finding(
                findings,
                'Critical',
                'Blocker',
                file_path,
                line_number,
                'Python requirement uses a direct URL, Git URL, or local file source.',
                raw_line,
                'dependency resolution or install time',
                'Replace with a reviewed package==version pin from the approved registry.',
            )
            continue

        if stripped.startswith(('-r ', '--requirement', '-c ', '--constraint')):
            add_finding(
                findings,
                'Moderate',
                'Needs investigation',
                file_path,
                line_number,
                'Python requirement delegates dependency resolution to another file.',
                raw_line,
                'dependency resolution or install time',
                'Review the referenced file in the same gate and ensure all direct dependencies are exactly pinned.',
            )
            continue

        match = PYTHON_REQUIREMENT_RE.match(stripped)
        if not match:
            add_finding(
                findings,
                'Critical',
                'Blocker',
                file_path,
                line_number,
                'Python requirement is not exactly pinned with package==version.',
                raw_line,
                'dependency resolution or install time',
                'Use exact package==version pins. Reject ranges, exclusions, wildcards, and unversioned entries.',
            )
            continue

        package_name = match.group('name').split('[', 1)[0]
        version = match.group('version')
        if '*' in version:
            add_finding(
                findings,
                'Critical',
                'Blocker',
                file_path,
                line_number,
                'Python requirement version contains a wildcard.',
                raw_line,
                'dependency resolution or install time',
                'Use an exact package==version pin without wildcards.',
            )
        if re.search(r'(a|b|rc|dev)\d*', version, re.IGNORECASE):
            add_finding(
                findings,
                'Important',
                'Needs investigation',
                file_path,
                line_number,
                'Python requirement appears to use a pre-release version.',
                raw_line,
                'dependency resolution or install time',
                'Confirm the pre-release package was intentionally selected and reviewed.',
            )
        releases.append(DependencyRelease('pypi', package_name, version, get_relative_path(file_path), line_number))


def inspect_package_json(
    file_path: Path,
    source_text: str,
    findings: list[Finding],
    releases: list[DependencyRelease],
) -> None:
    """Validate exact npm package pins and collect versions for release-age checks."""
    try:
        package_data = json.loads(source_text)
    except json.JSONDecodeError as exc:
        add_finding(
            findings,
            'Critical',
            'Blocker',
            file_path,
            exc.lineno,
            'package.json could not be parsed as JSON.',
            exc.msg,
            'dependency resolution or install time',
            'Fix JSON syntax before dependency review can complete.',
        )
        return

    sections = ('dependencies', 'devDependencies', 'optionalDependencies', 'peerDependencies')
    for section in sections:
        dependencies = package_data.get(section, {})
        if not isinstance(dependencies, dict):
            continue
        for package_name, specifier in sorted(dependencies.items()):
            evidence = f'{section}.{package_name}: {specifier}'
            if not isinstance(specifier, str) or not NPM_EXACT_VERSION_RE.match(specifier):
                add_finding(
                    findings,
                    'Critical',
                    'Blocker',
                    file_path,
                    1,
                    'npm dependency is not pinned to an exact version.',
                    evidence,
                    'dependency resolution or install time',
                    'Use exact semver versions. Reject ranges, dist-tags, workspace/file/Git/URL dependencies, and wildcards.',
                )
                continue
            if re.search(r'-(?:alpha|beta|rc|next|dev)', specifier, re.IGNORECASE):
                add_finding(
                    findings,
                    'Important',
                    'Needs investigation',
                    file_path,
                    1,
                    'npm dependency appears to use a pre-release version.',
                    evidence,
                    'dependency resolution or install time',
                    'Confirm the pre-release package was intentionally selected and reviewed.',
                )
            releases.append(DependencyRelease('npm', package_name, specifier, get_relative_path(file_path), 1))


def inspect_dockerfile(file_path: Path, source_text: str, findings: list[Finding]) -> None:
    """Validate Docker base image pinning and risky installer patterns."""
    for line_number, raw_line in enumerate(source_text.splitlines(), start=1):
        match = DOCKER_FROM_RE.match(raw_line)
        if match:
            image = match.group('image')
            if '@sha256:' not in image and (':' not in image.rsplit('/', 1)[-1] or image.endswith(':latest')):
                add_finding(
                    findings,
                    'Critical',
                    'Blocker',
                    file_path,
                    line_number,
                    'Docker base image is floating or uses latest.',
                    raw_line,
                    'build or deploy time',
                    'Pin Docker images to an immutable digest or reviewed exact version tag.',
                )
        if re.search(r'curl\s+[^|]+\|\s*(?:sh|bash)|wget\s+[^|]+\|\s*(?:sh|bash)', raw_line, re.IGNORECASE):
            add_finding(
                findings,
                'Important',
                'Needs investigation',
                file_path,
                line_number,
                'Dockerfile pipes downloaded content into a shell.',
                raw_line,
                'build time',
                'Download, verify, and execute installer content through a reviewed pinned checksum instead.',
            )


def inspect_workflow_file(file_path: Path, source_text: str, findings: list[Finding]) -> None:
    """Review GitHub Actions workflow dependency and token-risk markers."""
    for line_number, raw_line in enumerate(source_text.splitlines(), start=1):
        action_ref = GITHUB_ACTION_REF_RE.search(raw_line)
        if action_ref:
            full_ref = action_ref.group(1)
            ref = action_ref.group(2)
            if ref in {'main', 'master', 'latest'} or '${{' in ref:
                add_finding(
                    findings,
                    'Critical',
                    'Blocker',
                    file_path,
                    line_number,
                    'GitHub Action uses a floating or dynamic ref.',
                    raw_line,
                    'CI execution path',
                    'Pin actions to an immutable commit SHA or reviewed exact version.',
                )
            elif not re.fullmatch(r'[0-9a-f]{40}', ref, re.IGNORECASE):
                add_finding(
                    findings,
                    'Low',
                    'Acceptable with notes',
                    file_path,
                    line_number,
                    'GitHub Action is version-tagged rather than pinned to an immutable commit SHA.',
                    full_ref,
                    'CI execution path',
                    'Confirm this tag is an accepted repository convention or pin to a reviewed commit SHA.',
                )
        if 'pull_request_target' in raw_line:
            add_finding(
                findings,
                'Critical',
                'Blocker',
                file_path,
                line_number,
                'Workflow uses pull_request_target.',
                raw_line,
                'CI execution path with elevated token risk',
                'Do not run contributor-controlled code with privileged pull_request_target tokens.',
            )


def inspect_dependency_manifest(
    file_path: Path,
    source_text: str,
    findings: list[Finding],
    releases: list[DependencyRelease],
) -> None:
    """Apply dependency-policy checks for supported manifest types."""
    relative_path = get_relative_path(file_path)
    name = file_path.name.lower()

    if is_requirement_file(relative_path):
        inspect_requirements_file(file_path, source_text, findings, releases)
    elif name == 'package.json':
        inspect_package_json(file_path, source_text, findings, releases)
    elif name == 'dockerfile':
        inspect_dockerfile(file_path, source_text, findings)
    elif relative_path.startswith('.github/workflows/'):
        inspect_workflow_file(file_path, source_text, findings)


def parse_pypi_upload_time(package_name: str, version: str) -> datetime:
    """Return the oldest PyPI upload time for a package version."""
    url = f'https://pypi.org/pypi/{package_name}/{version}/json'
    with urlopen(url, timeout=20) as response:
        payload = json.loads(response.read().decode('utf-8'))
    upload_times = [item.get('upload_time_iso_8601') for item in payload.get('urls', [])]
    parsed_times = [datetime.fromisoformat(value.replace('Z', '+00:00')) for value in upload_times if value]
    if not parsed_times:
        raise ValueError('No PyPI upload timestamps found')
    return min(parsed_times)


def parse_npm_release_time(package_name: str, version: str) -> datetime:
    """Return the npm release time for a package version."""
    if not shutil.which('npm'):
        raise RuntimeError('npm is not available')
    result = subprocess.run(
        ['npm', 'view', f'{package_name}@{version}', 'time', '--json'],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or 'npm view failed')
    payload = json.loads(result.stdout)
    value = payload.get(version) if isinstance(payload, dict) else None
    if not value:
        raise ValueError('No npm release timestamp found')
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def verify_release_age(
    release: DependencyRelease,
    min_days: int,
    fail_on_unverified: bool,
    findings: list[Finding],
) -> None:
    """Verify that a dependency version is at least min_days old."""
    try:
        if release.ecosystem == 'pypi':
            release_time = parse_pypi_upload_time(release.package_name, release.version)
        elif release.ecosystem == 'npm':
            release_time = parse_npm_release_time(release.package_name, release.version)
        else:
            return
    except (HTTPError, URLError, OSError, RuntimeError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        severity = 'Critical' if fail_on_unverified else 'Important'
        verdict = 'Blocker' if fail_on_unverified else 'Needs investigation'
        add_finding(
            findings,
            severity,
            verdict,
            REPO_ROOT / release.file_path,
            release.line,
            f'Could not verify {release.ecosystem} release age for {release.package_name}=={release.version}.',
            str(exc),
            'dependency resolution or install time',
            'Verify release metadata from the trusted registry before approving this dependency change.',
        )
        return

    age_days = (datetime.now(timezone.utc) - release_time).total_seconds() / 86400
    if age_days < min_days:
        add_finding(
            findings,
            'Critical',
            'Blocker',
            REPO_ROOT / release.file_path,
            release.line,
            f'{release.ecosystem} package {release.package_name}=={release.version} is newer than {min_days} full days.',
            f'released {release_time.isoformat()}, age {age_days:.2f} days',
            'dependency resolution or install time',
            'Wait until the package version has aged at least seven full days or approve a documented exception.',
        )


def classify_path(relative_path: str) -> list[str]:
    """Return risk-area labels for a changed path."""
    labels: list[str] = []
    lowered_path = relative_path.lower()
    for label, markers in RISK_AREAS.items():
        for marker in markers:
            marker_lower = marker.lower()
            if marker_lower.startswith('.') and lowered_path.endswith(marker_lower):
                labels.append(label)
                break
            if marker_lower in lowered_path:
                labels.append(label)
                break
    return labels or ['other']


def summarize_changed_files(paths: list[Path]) -> dict[str, list[str]]:
    """Group changed files by risk area."""
    grouped: dict[str, list[str]] = {}
    for path in paths:
        relative_path = get_relative_path(path)
        for label in classify_path(relative_path):
            grouped.setdefault(label, []).append(relative_path)
    return grouped


def format_findings(findings: list[Finding]) -> str:
    """Return markdown for all findings."""
    if not findings:
        return 'No malicious indicators found in the reviewed scope. This is not a safety guarantee.\n'

    severity_order = {'Critical': 0, 'Important': 1, 'Moderate': 2, 'Low': 3}
    sorted_findings = sorted(findings, key=lambda item: (severity_order.get(item.severity, 99), item.file_path, item.line))
    lines: list[str] = []
    for index, finding in enumerate(sorted_findings, start=1):
        location = f'{finding.file_path}:{finding.line}' if finding.line else finding.file_path
        lines.extend(
            [
                f'{index}. **{finding.severity} - {finding.verdict}**',
                f'   - Location: `{location}`',
                f'   - Evidence: `{finding.evidence}`',
                f'   - Issue: {finding.message}',
                f'   - Reachability: {finding.reachability}',
                f'   - Recommended action: {finding.recommendation}',
                '',
            ]
        )
    return '\n'.join(lines)


def write_report(
    report_file: Path,
    paths: list[Path],
    grouped_paths: dict[str, list[str]],
    urls: set[str],
    releases: list[DependencyRelease],
    findings: list[Finding],
    base_sha: str | None,
    head_sha: str | None,
    verify_release_age_enabled: bool,
) -> None:
    """Write a markdown review report."""
    dependency_findings = [finding for finding in findings if 'dependency' in finding.reachability or 'CI execution' in finding.reachability]
    lines = [
        '# Malicious PR And File Security Review',
        '',
        f'- Review target: `{base_sha or "working tree"}` to `{head_sha or "working tree"}`',
        f'- Changed files reviewed: {len(paths)}',
        f'- Dependency release-age verification: {"enabled" if verify_release_age_enabled else "skipped"}',
        '',
        '## Changed-File Summary',
        '',
    ]
    for label, label_paths in sorted(grouped_paths.items()):
        lines.append(f'- **{label}**: {len(label_paths)}')
        for path in sorted(label_paths)[:20]:
            lines.append(f'  - `{path}`')
        if len(label_paths) > 20:
            lines.append(f'  - ... {len(label_paths) - 20} more')
    if not grouped_paths:
        lines.append('- No changed files found.')

    lines.extend(['', '## Dependency Policy Result', ''])
    if releases:
        lines.append(f'- Exact dependency pins collected for release-age review: {len(releases)}')
    else:
        lines.append('- No direct dependency pins were collected from changed manifests.')
    if dependency_findings:
        lines.append(f'- Dependency or CI policy findings: {len(dependency_findings)}')
    else:
        lines.append('- No dependency or CI policy findings were detected in reviewed manifests.')

    lines.extend(['', '## External Hosts And URLs', ''])
    if urls:
        for url in sorted(urls):
            lines.append(f'- `{url}`')
    else:
        lines.append('- No external URLs were found in reviewed changed lines.')

    lines.extend(['', '## Findings', '', format_findings(findings)])
    blockers = [finding for finding in findings if finding.verdict == 'Blocker']
    final_verdict = 'Block' if blockers else ('Needs investigation' if findings else 'No malicious indicators found in reviewed scope')
    lines.extend(['', '## Final Verdict', '', final_verdict, ''])
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text('\n'.join(lines), encoding='utf-8')


def escape_annotation_value(value: str) -> str:
    """Escape GitHub Actions annotation text."""
    return value.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A').replace(':', '%3A')


def emit_annotations(findings: list[Finding]) -> None:
    """Emit GitHub Actions annotations for findings."""
    for finding in findings:
        level = 'error' if finding.verdict == 'Blocker' else 'warning'
        message = f'{finding.severity} - {finding.message} Recommendation: {finding.recommendation}'
        print(
            f'::{level} file={finding.file_path},line={finding.line}::{escape_annotation_value(message)}'
        )


def run_review(args: argparse.Namespace) -> tuple[list[Finding], Path]:
    """Run the static review and return findings plus report path."""
    paths = normalize_paths(args.paths) if args.paths else get_changed_files(args.base_sha, args.head_sha)
    existing_paths = [path for path in paths if path.exists() and path.is_file()]
    findings: list[Finding] = []
    releases: list[DependencyRelease] = []
    urls: set[str] = set()

    for file_path in existing_paths:
        source_text = read_text(file_path)
        if source_text is None:
            inspect_binary_file(file_path, findings)
            continue

        changed_lines = get_changed_lines(file_path, args.base_sha, args.head_sha)
        urls.update(scan_text_patterns(file_path, source_text, changed_lines, args.full_file, findings))
        relative_path = get_relative_path(file_path)
        if is_dependency_manifest(relative_path):
            inspect_dependency_manifest(file_path, source_text, findings, releases)

    if args.verify_release_age:
        for release in releases:
            verify_release_age(release, args.min_release_age_days, args.fail_on_unverified_release_age, findings)

    report_file = Path(args.report_file)
    if not report_file.is_absolute():
        report_file = REPO_ROOT / report_file
    write_report(
        report_file,
        existing_paths,
        summarize_changed_files(existing_paths),
        urls,
        releases,
        findings,
        args.base_sha,
        args.head_sha,
        args.verify_release_age,
    )
    return findings, report_file


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(description='Static malicious PR and file security review checker.')
    parser.add_argument('paths', nargs='*', help='Explicit files to review. Defaults to git diff paths.')
    parser.add_argument('--base-sha', help='Base commit for changed-line review.')
    parser.add_argument('--head-sha', help='Head commit for changed-line review.')
    parser.add_argument('--full-file', action='store_true', help='Scan full files instead of only changed lines.')
    parser.add_argument('--verify-release-age', action='store_true', help='Query trusted registries for dependency age checks.')
    parser.add_argument('--fail-on-unverified-release-age', action='store_true', help='Treat registry lookup failures as blockers.')
    parser.add_argument('--min-release-age-days', type=int, default=7, help='Minimum accepted dependency version age.')
    parser.add_argument('--fail-on-findings', action='store_true', help='Fail on any finding, not only blockers.')
    parser.add_argument(
        '--report-file',
        default='artifacts/malicious-pr-security-review.md',
        help='Markdown report destination.',
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    findings, report_file = run_review(args)
    emit_annotations(findings)
    print(f'Malicious PR security review report written to {get_relative_path(report_file)}')

    blockers = [finding for finding in findings if finding.verdict == 'Blocker']
    if blockers:
        print(f'Found {len(blockers)} blocker finding(s).')
        return 1
    if args.fail_on_findings and findings:
        print(f'Found {len(findings)} finding(s) and --fail-on-findings was set.')
        return 1
    print('No blocker findings detected in reviewed scope.')
    return 0


if __name__ == '__main__':
    sys.exit(main())