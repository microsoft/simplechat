# functions_bitbucket_operations.py
"""Bootstrap-free, read-only Bitbucket contracts and bounded REST adapters."""

import difflib
import hashlib
import json
import re
from copy import deepcopy
from urllib.parse import parse_qs, quote, urlsplit

import requests

from functions_outbound_destinations import OutboundDestinationError, normalize_outbound_url
from functions_outbound_http import create_guarded_session


BITBUCKET_PLUGIN_TYPE = "bitbucket"
MAX_BYTES = 1000000
MAX_FILE_BYTES = 250000
PAGE_SIZE = 50
TIMEOUT = (10, 30)


class BitbucketError(ValueError):
    """A stable provider-independent error, safe for client responses."""

    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code = code
        self.public_message = message
        self.status = status


def fail(code, message, status=400):
    raise BitbucketError(code, message, status)


def text(value, label, *, optional=False, limit=255):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        fail("configuration_invalid", f"{label} is invalid.")
    if not value and not optional:
        fail("configuration_invalid", f"{label} is required.")
    return value


def branch_name(value, *, optional=False):
    value = text(value, "Branch", optional=optional)
    if value and (
        value.startswith(("-", "/", "refs/")) or value.endswith(("/", ".", ".lock"))
        or ".." in value or "//" in value or "@{" in value or value == "@"
        or re.search(r"[\s~^:?*\[\\]", value)
    ):
        fail("branch_invalid", "Use an exact branch name, not a tag, commit, or ref expression.")
    return value


def normalize_bitbucket_manifest(manifest, *, allow_empty=False):
    result = deepcopy(manifest)
    fields = result.get("additionalFields") or {}
    if not isinstance(fields, dict):
        fail("configuration_invalid", "Bitbucket configuration must be an object.")
    edition = fields.get("edition", "data_center")
    if edition not in {"data_center", "cloud"}:
        fail("configuration_invalid", "Select Bitbucket Data Center or Cloud.")
    endpoint = result.get("endpoint") or ("https://api.bitbucket.org" if edition == "cloud" else "")
    try:
        target = normalize_outbound_url(endpoint)
    except OutboundDestinationError as error:
        raise BitbucketError("destination_invalid", error.public_message) from None
    parsed = urlsplit(target.url)
    if target.scheme != "https" or parsed.query or parsed.fragment:
        fail("destination_invalid", "Bitbucket requires an HTTPS base URL without a query or fragment.")
    if edition == "cloud" and target.url.rstrip("/") != "https://api.bitbucket.org":
        fail("destination_invalid", "Bitbucket Cloud API requests must use https://api.bitbucket.org.")
    method = fields.get("auth_method", "oauth")
    if method not in {"oauth", "bearer_token", "username_password"}:
        fail("configuration_invalid", "Choose OAuth, a bearer token, or an email and API token.")
    if edition != "cloud" and method == "username_password":
        fail("configuration_invalid", "Data Center requires OAuth or a bearer HTTP access token.")
    repos = fields.get("repositories", [])
    if not isinstance(repos, list) or len(repos) > 50 or (not repos and not allow_empty):
        fail("repository_required", "Select between one and 50 permitted repositories.")
    normalized, seen = [], set()
    for repo in repos:
        if not isinstance(repo, dict) or set(repo) - {"id", "project", "slug", "name", "branch_mode", "default_branch"}:
            fail("repository_invalid", "Repository configuration is invalid.")
        item = {key: text(repo.get(key, ""), key, optional=key == "name") for key in ("id", "project", "slug", "name")}
        for key in ("project", "slug"):
            if not re.fullmatch(r"[A-Za-z0-9_{}~.-]+", item[key]) or item[key] in {".", ".."}:
                fail("repository_invalid", "Repository project/workspace or slug is invalid.")
        if item["id"] in seen:
            fail("repository_invalid", "Repository selections must be unique.")
        seen.add(item["id"])
        item["branch_mode"] = repo.get("branch_mode", "any")
        item["default_branch"] = branch_name(repo.get("default_branch", ""), optional=True)
        if item["branch_mode"] not in {"fixed", "any"} or (item["branch_mode"] == "fixed" and not item["default_branch"]):
            fail("branch_invalid", "A fixed repository requires its branch name.")
        normalized.append(item)
    result["type"] = BITBUCKET_PLUGIN_TYPE
    result["endpoint"] = target.url.rstrip("/")
    result["additionalFields"] = {
        **fields, "edition": edition, "auth_method": method, "repositories": normalized,
    }
    if method == "oauth":
        text((result.get("auth") or {}).get("identity", ""), "OAuth client ID", optional=allow_empty)
        if result.get("identity_id") or result.get("credential_requirements", {}).get("slots"):
            fail("configuration_invalid", "OAuth connections cannot use token identity bindings.")
    return result


def policy_fingerprint(manifest):
    manifest = normalize_bitbucket_manifest(manifest, allow_empty=True)
    fields = manifest["additionalFields"]
    material = [manifest["endpoint"], fields["edition"], fields["auth_method"],
                fields["repositories"], (manifest.get("auth") or {}).get("identity", "") if fields["auth_method"] == "oauth" else ""]
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def bounded_response(response, *, limit=MAX_BYTES, as_json=True):
    try:
        status = response.status_code
        if status != 200:
            codes = {
                401: ("reconnect_required", "Bitbucket rejected the credentials. Reconnect or replace your token."),
                403: ("access_denied", "Bitbucket denied access to this repository or branch."),
                404: ("not_found", "The Bitbucket repository, branch, or file was not found."),
                429: ("rate_limited", "Bitbucket rate-limited this request. Try again later."),
            }
            code, message = codes.get(status, ("provider_failed", "Bitbucket did not return a successful response."))
            fail(code, message, status if status in codes else 502)
        data = bytearray()
        for chunk in response.iter_content(chunk_size=8192):
            data.extend(chunk)
            if len(data) > limit:
                fail("result_too_large", "Bitbucket content exceeds the read limit. Request a smaller file or comparison.", 413)
        if as_json:
            value = json.loads(data)
            if not isinstance(value, dict):
                fail("response_invalid", "Bitbucket returned a non-object JSON response.", 502)
            return value
        if b"\x00" in data:
            fail("binary_file", "Binary files cannot be reviewed as source text.", 415)
        return data.decode("utf-8-sig")
    except (UnicodeError, json.JSONDecodeError):
        fail("response_invalid", "Bitbucket returned unsupported text or a non-JSON response.", 502)
    finally:
        response.close()


class BitbucketClient:
    """Only explicit repository GET operations; no arbitrary URLs or write methods."""

    def __init__(self, manifest, auth, *, session_factory=create_guarded_session):
        self.manifest = normalize_bitbucket_manifest(manifest, allow_empty=True)
        self.fields = self.manifest["additionalFields"]
        self.cloud = self.fields["edition"] == "cloud"
        self.base = self.manifest["endpoint"] + ("/2.0" if self.cloud else "/rest/api/1.0")
        self.auth = auth
        self.session_factory = session_factory

    def get(self, path, params=None, *, raw=False, limit=MAX_BYTES):
        if not path.startswith("/") or "://" in path or "\\" in path:
            fail("request_invalid", "Invalid Bitbucket operation.")
        headers = {"Accept": "text/plain" if raw else "application/json"}
        auth = None
        if not self.auth.get("secret"):
            fail("credentials_required", "Select a Bitbucket token identity or connect your account.", 409)
        if self.auth.get("method") == "username_password":
            auth = (self.auth["username"], self.auth["secret"])
        else:
            headers["Authorization"] = f"Bearer {self.auth['secret']}"
        try:
            with self.session_factory() as session:
                response = session.get(self.base + path, params=params, headers=headers, auth=auth,
                                       timeout=TIMEOUT, stream=True, allow_redirects=False)
                return bounded_response(response, limit=limit, as_json=not raw)
        except requests.RequestException:
            fail("connection_failed", "Cannot reach Bitbucket. Check private connectivity, DNS, and trusted TLS certificates.", 502)
        except OutboundDestinationError as error:
            raise BitbucketError("destination_invalid", error.public_message) from None

    def page(self, path, cursor=0, params=None, *, page_size=PAGE_SIZE):
        if self.cloud:
            if type(cursor) not in {int, str} or (type(cursor) is int and cursor < 0):
                fail("cursor_invalid", "Invalid Bitbucket page.")
            text(str(cursor), "Page token", limit=1024)
        else:
            if isinstance(cursor, str) and cursor.isascii() and cursor.isdecimal():
                cursor = int(cursor)
            if type(cursor) is not int or cursor < 0 or cursor > 10000:
                fail("cursor_invalid", "Invalid Bitbucket page.")
        query = {"pagelen": page_size, "page": cursor or 1} if self.cloud else {"limit": page_size, "start": cursor}
        value = self.get(path, {**(params or {}), **query})
        rows = value.get("values")
        if not isinstance(rows, list) or len(rows) > page_size or any(not isinstance(row, dict) for row in rows):
            fail("response_invalid", "Bitbucket returned an invalid result page.", 502)
        following = None
        if self.cloud and value.get("next"):
            # Only carry the opaque page token forward, never a provider-supplied destination.
            following_url = value["next"]
            if not isinstance(following_url, str) or len(following_url) > 4096:
                fail("response_invalid", "Bitbucket returned invalid pagination.", 502)
            parsed, expected = urlsplit(following_url), urlsplit(self.base + path)
            values = parse_qs(parsed.query)
            if (parsed.scheme != expected.scheme or parsed.netloc != expected.netloc
                    or parsed.path.rstrip("/") != expected.path.rstrip("/") or parsed.fragment
                    or set(values) - {"page", "pagelen", *(params or {})}
                    or len(values.get("page", [])) != 1
                    or values.get("pagelen", [str(page_size)]) != [str(page_size)]
                    or any(key in values and values[key] != [str(value)] for key, value in (params or {}).items())):
                fail("response_invalid", "Bitbucket returned invalid pagination.", 502)
            following = values["page"][0]
            if (not following or len(following) > 1024 or any(ord(char) < 32 or ord(char) == 127 for char in following)
                    or following == str(query["page"])):
                fail("response_invalid", "Bitbucket returned invalid pagination.", 502)
        elif not self.cloud:
            if type(value.get("isLastPage")) is not bool:
                fail("response_invalid", "Bitbucket returned invalid pagination.", 502)
            if not value["isLastPage"]:
                following = value.get("nextPageStart")
                if type(following) is not int or following <= cursor or following > 10000:
                    fail("response_invalid", "Bitbucket returned invalid pagination.", 502)
        return rows, following

    def root(self, repo):
        if self.cloud:
            return f"/repositories/{quote(repo['project'], safe='')}/{quote(repo['slug'], safe='')}"
        return f"/projects/{quote(repo['project'], safe='')}/repos/{quote(repo['slug'], safe='')}"

    def verify_repository(self, repo):
        value = self.get(self.root(repo))
        actual = value.get("uuid") if self.cloud else str(value.get("id", ""))
        if actual != repo["id"]:
            fail("repository_changed", "The repository identity changed. Ask the action author to select it again.", 409)
        return value

    def repository(self, repository):
        repos = self.fields["repositories"]
        candidates = [r for r in repos if r["id"] == repository] if repository else repos
        if len(candidates) != 1:
            fail("repository_required", "Choose one permitted repository by its ID.")
        repo = candidates[0]
        self.verify_repository(repo)
        return repo

    def repositories(self):
        result = []
        for repo in self.fields["repositories"]:
            try:
                self.verify_repository(repo)
            except BitbucketError as exc:
                if exc.status in {403, 404}:
                    continue
                raise
            result.append({"id": repo["id"], "name": repo["name"] or repo["slug"],
                           "branch_mode": repo["branch_mode"], "default_branch": repo["default_branch"]})
        return {"repositories": result}

    def discover(self, project, cursor=0):
        text(project, "Project or workspace")
        if not re.fullmatch(r"[A-Za-z0-9_{}~.-]+", project) or project in {".", ".."}:
            fail("repository_invalid", "Specify a project key or Cloud workspace identifier.")
        path = f"/repositories/{quote(project, safe='')}" if self.cloud else f"/projects/{quote(project, safe='')}/repos"
        rows, following = self.page(path, cursor)
        results = []
        for row in rows:
            item = {"id": row.get("uuid", "") if self.cloud else str(row.get("id", "")), "project": project,
                    "slug": row.get("slug", ""), "name": row.get("name") or row.get("slug", ""),
                    "branch_mode": "any", "default_branch": ""}
            try:
                normalize_bitbucket_manifest({**self.manifest, "additionalFields": {
                    **self.fields, "repositories": [item],
                }})
            except BitbucketError:
                fail("response_invalid", "Bitbucket returned an invalid repository.", 502)
            results.append(item)
        return {"repositories": results, "next_cursor": following}

    def resolve(self, repo, branch=""):
        configured = repo["default_branch"]
        branch = branch_name(branch or configured, optional=True)
        if repo["branch_mode"] == "fixed" and branch != configured:
            fail("branch_denied", "This action only permits the configured fixed branch.", 403)
        if not branch:
            info = self.get(self.root(repo)) if self.cloud else self.get(self.root(repo) + "/branches/default")
            if self.cloud and not isinstance(info.get("mainbranch"), dict):
                fail("response_invalid", "Bitbucket returned no valid default branch.", 502)
            branch = info["mainbranch"].get("name") if self.cloud else info.get("displayId")
            branch = branch_name(branch)
        if self.cloud:
            value = self.get(self.root(repo) + f"/refs/branches/{quote(branch, safe='')}")
            if not isinstance(value.get("target"), dict):
                fail("response_invalid", "Bitbucket returned an invalid branch commit.", 502)
            commit = value["target"].get("hash")
        else:
            cursor, matches = 0, []
            for _page in range(10):
                rows, cursor = self.page(self.root(repo) + "/branches", cursor, {"filterText": branch})
                matches.extend(r for r in rows if r.get("id") == f"refs/heads/{branch}")
                if matches or cursor is None:
                    break
            if not matches and cursor is not None:
                fail("branch_lookup_limit", "Bitbucket returned too many similar branch names to resolve this branch safely.", 413)
            if len(matches) != 1:
                fail("branch_not_found", "The exact configured or requested branch was not found.", 404)
            commit = matches[0].get("latestCommit")
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40,64}", commit):
            fail("response_invalid", "Bitbucket returned an invalid branch commit.", 502)
        return branch, commit

    def branches(self, repository="", cursor=0):
        repo = self.repository(repository)
        if repo["branch_mode"] == "fixed":
            branch, commit = self.resolve(repo)
            return {"branches": [{"name": branch, "commit": commit}], "next_cursor": None}
        path = "/refs/branches" if self.cloud else "/branches"
        rows, following = self.page(self.root(repo) + path, cursor)
        names = [r.get("name") if self.cloud else r.get("displayId") for r in rows]
        try:
            for name in names:
                branch_name(name)
        except BitbucketError:
            fail("response_invalid", "Bitbucket returned an invalid branch name.", 502)
        return {"branches": [{"name": name} for name in names], "next_cursor": following}

    def source(self, repo, commit, path, *, raw=False, cursor=0):
        if not self.cloud:
            if isinstance(cursor, str) and cursor.isascii() and cursor.isdecimal():
                cursor = int(cursor)
            if type(cursor) is not int or not 0 <= cursor <= 10000:
                fail("cursor_invalid", "Invalid Bitbucket page.")
        text(path, "File path", optional=not raw, limit=2048)
        if path.startswith(("/", "\\")) or any(p in {".", ".."} for p in path.split("/")) or "\\" in path:
            fail("path_invalid", "Use a repository-relative path without traversal.")
        encoded = quote(path, safe="/")
        if self.cloud:
            route = self.root(repo) + f"/src/{commit}/{encoded}"
            if not raw and not route.endswith("/"):
                route += "/"
            return self.get(route, raw=True, limit=MAX_FILE_BYTES) if raw else self.page(route, cursor)
        route = self.root(repo) + ("/raw/" if raw else "/browse/") + encoded
        if raw:
            return self.get(route, {"at": commit}, raw=True, limit=MAX_FILE_BYTES)
        value = self.get(route, {"at": commit, "limit": PAGE_SIZE, "start": cursor})
        children = value.get("children")
        if not isinstance(children, dict):
            fail("path_invalid", "The requested path is not a directory.")
        rows = children.get("values")
        following = None if children.get("isLastPage") is True else children.get("nextPageStart")
        if (not isinstance(rows, list) or len(rows) > PAGE_SIZE or any(not isinstance(row, dict) for row in rows)
                or type(children.get("isLastPage")) is not bool
                or (not children["isLastPage"] and (type(following) is not int or not cursor < following <= 10000))):
            fail("response_invalid", "Bitbucket returned an invalid directory page.", 502)
        return rows, following

    def tree(self, repository="", branch="", path="", cursor=0):
        repo = self.repository(repository)
        name, commit = self.resolve(repo, branch)
        rows, following = self.source(repo, commit, path, cursor=cursor)
        entries = []
        for row in rows:
            value = row.get("path")
            if not self.cloud:
                if not isinstance(value, dict):
                    fail("response_invalid", "Bitbucket returned an invalid directory entry.", 502)
                value = value.get("toString")
            if not isinstance(value, str) or not value:
                fail("response_invalid", "Bitbucket returned an invalid directory entry.", 502)
            entries.append({"path": value, "type": row.get("type")})
        return {"repository": repo["id"], "branch": name, "commit": commit,
                "entries": entries, "next_cursor": following}

    def read_file(self, repository="", branch="", path="", start_line=1, max_lines=200):
        if type(start_line) is not int or start_line < 1 or type(max_lines) is not int or not 1 <= max_lines <= 500:
            fail("range_invalid", "Choose a positive start line and between one and 500 lines.")
        repo = self.repository(repository)
        name, commit = self.resolve(repo, branch)
        content = self.source(repo, commit, path, raw=True)
        lines = content.splitlines()
        if start_line > max(1, len(lines)):
            fail("range_invalid", "The requested start line is beyond the end of this file.")
        end = min(len(lines), start_line - 1 + max_lines)
        return {"repository": repo["id"], "branch": name, "commit": commit, "path": path,
                "start_line": start_line, "end_line": end,
                "content": "\n".join(lines[start_line - 1:end]), "total_lines": len(lines),
                "truncated": end < len(lines), "next_line": end + 1 if end < len(lines) else None}

    def compare(self, repository, base_branch, target_branch, cursor=0):
        repo = self.repository(repository)
        base_name, base = self.resolve(repo, base_branch)
        target_name, target = self.resolve(repo, target_branch)
        root = self.root(repo)
        if self.cloud:
            merge = self.get(root + f"/merge-base/{base}..{target}").get("hash")
        else:
            merge = self.get(root + f"/commits/{base}/merge-base", {"otherCommitId": target}).get("id")
        if not isinstance(merge, str) or not re.fullmatch(r"[0-9a-f]{40,64}", merge):
            fail("response_invalid", "Bitbucket could not establish a merge base.", 502)
        if self.cloud:
            rows, following = self.page(root + f"/diffstat/{target}..{merge}", cursor, {"topic": "false"}, page_size=10)
        else:
            rows, following = self.page(root + "/changes", cursor, {"since": merge, "until": target}, page_size=10)

        def changed_path(value):
            if value is None:
                return None
            key = "path" if self.cloud else "toString"
            if not isinstance(value, dict) or not isinstance(value.get(key), str) or not value[key]:
                fail("response_invalid", "Bitbucket returned an invalid changed-file path.", 502)
            return value[key]

        paths = []
        for row in rows:
            if self.cloud:
                old, new = changed_path(row.get("old")), changed_path(row.get("new"))
            else:
                old = None if row.get("type") == "ADD" else changed_path(row.get("srcPath") or row.get("path"))
                new = None if row.get("type") == "DELETE" else changed_path(row.get("path"))
            if old is None and new is None:
                fail("response_invalid", "Bitbucket returned a change without a file path.", 502)
            paths.append((old, new))
        # Bounded per-file reads make provider patch truncation impossible to mistake for a complete review.
        files, total = [], 0
        for old, new in paths:
            try:
                before = self.source(repo, merge, old, raw=True) if old else ""
                after = self.source(repo, target, new, raw=True) if new else ""
                before_lines, after_lines = before.splitlines(True), after.splitlines(True)
                if max(len(before_lines), len(after_lines)) > 10000:
                    files.append({"old_path": old, "path": new, "omitted": "comparison_line_limit"})
                    continue
                changes = difflib.unified_diff(before_lines, after_lines, fromfile=old or "/dev/null", tofile=new or "/dev/null")
                patch = "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n" for line in changes)
                if total + len(patch.encode()) > MAX_BYTES:
                    files.append({"old_path": old, "path": new, "omitted": "comparison_byte_limit"})
                    continue
                total += len(patch.encode())
                files.append({"old_path": old, "path": new, "patch": patch})
            except BitbucketError as exc:
                if exc.code not in {"binary_file", "result_too_large", "response_invalid"}:
                    raise
                files.append({"old_path": old, "path": new, "omitted": exc.code})
        result = {"repository": repo["id"], "base_branch": base_name, "base_commit": base,
                  "target_branch": target_name, "target_commit": target, "merge_base": merge,
                  "comparison_mode": "merge_base_to_target", "files": files, "next_cursor": following,
                  "truncated": following is not None or any("omitted" in file for file in files)}
        for file in reversed(files):
            if len(json.dumps(result).encode("utf-8")) <= MAX_BYTES:
                break
            file.pop("patch", None)
            file["omitted"] = "comparison_byte_limit"
            result["truncated"] = True
        return result
