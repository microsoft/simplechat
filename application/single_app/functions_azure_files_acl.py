# functions_azure_files_acl.py
"""Parse Azure Files security descriptors (SDDL) and decide whether a user can read a file.

Azure Files OAuth reads use backup intent, which bypasses NTFS permissions, so SimpleChat
evaluates each file's DACL itself before any of the file's content reaches a model.

Evaluation mirrors Windows' ordered DACL check for FILE_READ_DATA and fails closed: when
membership in a referenced principal, a conditional or object ACE, or rights granted only
through generic bits could change the answer, the outcome is ``unverified`` rather than
``allowed``. This module performs no I/O; callers supply a membership function.
"""

import re
from dataclasses import dataclass
from typing import Callable, FrozenSet, Iterable, Optional, Tuple

OUTCOME_ALLOWED = "allowed"
OUTCOME_DENIED = "denied"
OUTCOME_UNVERIFIED = "unverified"

REASON_ACL_ALLOW = "acl_allow"
REASON_ACL_NULL_DACL = "acl_null_dacl"
REASON_ACL_EXPLICIT_DENY = "acl_explicit_deny"
REASON_ACL_NO_ALLOW = "acl_no_allow"
REASON_ACL_EMPTY = "acl_empty"
REASON_SID_UNRESOLVED = "sid_unresolved"
REASON_ACL_UNSUPPORTED = "acl_unsupported"
REASON_ACL_PARSE_ERROR = "acl_parse_error"
REASON_ACL_MISSING = "acl_missing"

MEMBER = "member"
NOT_MEMBER = "not_member"
UNKNOWN = "unknown"

FILE_READ_DATA = 0x1
GENERIC_ALL = 0x10000000
GENERIC_EXECUTE = 0x20000000
GENERIC_WRITE = 0x40000000
GENERIC_READ = 0x80000000
# GENERIC_READ and GENERIC_ALL map to rights that include FILE_READ_DATA for files.
GENERIC_RIGHTS_INCLUDING_READ = GENERIC_READ | GENERIC_ALL

MAX_SDDL_LENGTH = 65536
MAX_ACE_COUNT = 1820

EVERYONE_SID = "S-1-1-0"
CREATOR_OWNER_SID = "S-1-3-0"
CREATOR_GROUP_SID = "S-1-3-1"
OWNER_RIGHTS_SID = "S-1-3-4"
NETWORK_SID = "S-1-5-2"
AUTHENTICATED_USERS_SID = "S-1-5-11"
BUILTIN_USERS_SID = "S-1-5-32-545"
DOMAIN_USERS_RID = 513

SDDL_RIGHTS_ALIASES = {
    "GA": GENERIC_ALL,
    "GR": GENERIC_READ,
    "GW": GENERIC_WRITE,
    "GX": GENERIC_EXECUTE,
    "RC": 0x00020000,
    "SD": 0x00010000,
    "WD": 0x00040000,
    "WO": 0x00080000,
    "RP": 0x00000010,
    "WP": 0x00000020,
    "CC": 0x00000001,
    "DC": 0x00000002,
    "LC": 0x00000004,
    "SW": 0x00000008,
    "LO": 0x00000080,
    "DT": 0x00000040,
    "CR": 0x00000100,
    "FA": 0x001F01FF,
    "FR": 0x00120089,
    "FW": 0x00120116,
    "FX": 0x001200A0,
    "KA": 0x000F003F,
    "KR": 0x00020019,
    "KW": 0x00020006,
    "KX": 0x00020019,
}

# Machine- and domain-independent SDDL SID aliases.
SDDL_SID_ALIASES = {
    "WD": EVERYONE_SID,
    "CO": CREATOR_OWNER_SID,
    "CG": CREATOR_GROUP_SID,
    "OW": OWNER_RIGHTS_SID,
    "NU": NETWORK_SID,
    "BT": "S-1-5-3",
    "IU": "S-1-5-4",
    "SU": "S-1-5-6",
    "AN": "S-1-5-7",
    "ED": "S-1-5-9",
    "PS": "S-1-5-10",
    "AU": AUTHENTICATED_USERS_SID,
    "RC": "S-1-5-12",
    "SY": "S-1-5-18",
    "LS": "S-1-5-19",
    "NS": "S-1-5-20",
    "WR": "S-1-5-33",
    "BA": "S-1-5-32-544",
    "BU": BUILTIN_USERS_SID,
    "BG": "S-1-5-32-546",
    "PU": "S-1-5-32-547",
    "AO": "S-1-5-32-548",
    "SO": "S-1-5-32-549",
    "PO": "S-1-5-32-550",
    "BO": "S-1-5-32-551",
    "RE": "S-1-5-32-552",
    "RU": "S-1-5-32-554",
    "RD": "S-1-5-32-555",
    "NO": "S-1-5-32-556",
    "MU": "S-1-5-32-558",
    "CD": "S-1-5-32-574",
    "AC": "S-1-15-2-1",
    "LW": "S-1-16-4096",
    "ME": "S-1-16-8192",
    "HI": "S-1-16-12288",
    "SI": "S-1-16-16384",
}
# Aliases relative to a domain or machine that the SDDL string does not name. They are kept
# as ``alias:<XX>`` because the SID behind them cannot be reconstructed here.
SDDL_RELATIVE_SID_ALIASES = {"DA", "DU", "DG", "DC", "DD", "CA", "EA", "SA", "PA", "RS", "RO", "LA", "LG", "CN", "AP", "KA", "EK"}
# Relative aliases for administrator, service, machine and guest principals. SimpleChat does not
# treat its signed-in users as members of these.
PRIVILEGED_RELATIVE_SID_ALIASES = {"DA", "DG", "DC", "DD", "CA", "EA", "SA", "PA", "RS", "RO", "LA", "LG", "CN", "KA", "EK"}

# Principals present in a network (SMB) logon session for any authenticated user.
ALWAYS_MEMBER_SIDS = frozenset({EVERYONE_SID, AUTHENTICATED_USERS_SID, NETWORK_SID})
# System, service, placeholder, logon-type, integrity and administrator principals. A user
# reaching a share through SimpleChat is never treated as one of these.
NEVER_MEMBER_SIDS = frozenset({
    CREATOR_OWNER_SID,
    CREATOR_GROUP_SID,
    "S-1-5-3",
    "S-1-5-4",
    "S-1-5-6",
    "S-1-5-7",
    "S-1-5-9",
    "S-1-5-10",
    "S-1-5-12",
    "S-1-5-18",
    "S-1-5-19",
    "S-1-5-20",
    "S-1-5-33",
    "S-1-5-32-544",
    "S-1-5-32-546",
    "S-1-5-32-547",
    "S-1-5-32-548",
    "S-1-5-32-549",
    "S-1-5-32-550",
    "S-1-5-32-551",
    "S-1-5-32-552",
    "S-1-5-32-554",
    "S-1-5-32-555",
    "S-1-5-32-556",
    "S-1-5-32-558",
    "S-1-5-32-574",
    "S-1-15-2-1",
    "S-1-16-4096",
    "S-1-16-8192",
    "S-1-16-12288",
    "S-1-16-16384",
})
# Well-known domain RIDs for built-in administrator, guest, machine and service accounts.
PRIVILEGED_DOMAIN_RIDS = frozenset({498, 500, 501, 502, 512, 514, 515, 516, 517, 518, 519, 520, 521, 553})

ACE_POLARITY = {
    "A": "allow",
    "D": "deny",
    "OA": "allow",
    "OD": "deny",
    "XA": "allow",
    "XD": "deny",
    "ZA": "allow",
}
# Audit, alarm, label and attribute ACEs never grant or deny access.
NON_ACCESS_ACE_TYPES = frozenset({"AU", "AL", "OU", "OL", "ML", "XU", "SP", "RA"})
SUPPORTED_ACE_TYPES = frozenset({"A", "D"})
ACE_FLAG_TOKENS = frozenset({"CI", "OI", "NP", "IO", "ID", "SA", "FA", "TP", "CR"})
DACL_FLAG_TOKENS = ("NO_ACCESS_CONTROL", "AR", "AI", "P")

_SID_PATTERN = re.compile(r"^S-1-\d+(-\d+)+$", re.IGNORECASE)
_DOMAIN_SID_PATTERN = re.compile(r"^S-1-5-21-(\d+)-(\d+)-(\d+)-(\d+)$")
_COMPONENT_PATTERN = re.compile(r"[OGDS]:")


class SddlParseError(ValueError):
    """The SDDL string could not be parsed; the caller must treat the file as unverified."""


@dataclass(frozen=True)
class AccessControlEntry:
    ace_type: str
    flags: FrozenSet[str]
    mask: int
    sid: str


@dataclass(frozen=True)
class SecurityDescriptor:
    owner_sid: str
    group_sid: str
    dacl_present: bool
    dacl_null: bool
    dacl_flags: FrozenSet[str]
    dacl: Tuple[AccessControlEntry, ...]


@dataclass(frozen=True)
class AccessDecision:
    outcome: str
    reason: str
    unresolved_sids: Tuple[str, ...] = ()
    unsupported_aces: Tuple[str, ...] = ()

    @property
    def allowed(self) -> bool:
        return self.outcome == OUTCOME_ALLOWED


def normalize_sid(value: str) -> str:
    """Return a SID in canonical ``S-1-...`` form, or ``""`` when it is not a SID."""
    text = str(value or "").strip()
    if not _SID_PATTERN.match(text):
        return ""
    return f"S{text[1:]}"


def domain_sid_and_rid(sid: str) -> Tuple[str, Optional[int]]:
    """Split ``S-1-5-21-a-b-c-rid`` into its domain SID and relative ID."""
    match = _DOMAIN_SID_PATTERN.match(sid or "")
    if not match:
        return "", None
    return f"S-1-5-21-{match.group(1)}-{match.group(2)}-{match.group(3)}", int(match.group(4))


def _resolve_sid_token(token: str) -> str:
    text = str(token or "").strip()
    sid = normalize_sid(text)
    if sid:
        return sid
    alias = text.upper()
    if alias in SDDL_SID_ALIASES:
        return SDDL_SID_ALIASES[alias]
    if alias in SDDL_RELATIVE_SID_ALIASES:
        return f"alias:{alias}"
    raise SddlParseError("The security descriptor contains an unrecognized principal.")


def _parse_rights(text: str) -> int:
    value = str(text or "").strip()
    if not value:
        raise SddlParseError("An ACE has no access rights.")
    if value[:2].lower() == "0x":
        try:
            return int(value, 16)
        except ValueError as error:
            raise SddlParseError("An ACE has invalid access rights.") from error
    if value.isdigit():
        return int(value)
    if len(value) % 2:
        raise SddlParseError("An ACE has invalid access rights.")
    mask = 0
    for index in range(0, len(value), 2):
        alias = value[index:index + 2].upper()
        if alias not in SDDL_RIGHTS_ALIASES:
            raise SddlParseError("An ACE has an unrecognized access right.")
        mask |= SDDL_RIGHTS_ALIASES[alias]
    return mask


def _parse_ace_flags(text: str) -> FrozenSet[str]:
    value = str(text or "").strip().upper()
    if len(value) % 2:
        raise SddlParseError("An ACE has invalid flags.")
    flags = set()
    for index in range(0, len(value), 2):
        flag = value[index:index + 2]
        if flag not in ACE_FLAG_TOKENS:
            raise SddlParseError("An ACE has an unrecognized flag.")
        flags.add(flag)
    return frozenset(flags)


def _parse_ace(text: str) -> AccessControlEntry:
    parts = text.split(";", 5)
    if len(parts) != 6:
        raise SddlParseError("An ACE is malformed.")
    ace_type = parts[0].strip().upper()
    if ace_type not in ACE_POLARITY and ace_type not in NON_ACCESS_ACE_TYPES:
        raise SddlParseError("An ACE has an unrecognized type.")
    # A conditional or resource-attribute ACE carries an expression after the SID.
    sid_token = parts[5].split(";", 1)[0]
    return AccessControlEntry(
        ace_type=ace_type,
        flags=_parse_ace_flags(parts[1]),
        mask=_parse_rights(parts[2]),
        sid=_resolve_sid_token(sid_token),
    )


def _split_aces(text: str, start: int) -> Tuple[Tuple[str, ...], int]:
    aces = []
    index = start
    while index < len(text) and text[index] == "(":
        depth = 0
        in_quote = False
        cursor = index
        while cursor < len(text):
            char = text[cursor]
            if in_quote:
                if char == '"':
                    in_quote = False
            elif char == '"':
                in_quote = True
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    break
            cursor += 1
        if cursor >= len(text):
            raise SddlParseError("An ACE is not terminated.")
        aces.append(text[index + 1:cursor])
        if len(aces) > MAX_ACE_COUNT:
            raise SddlParseError("The security descriptor has too many ACEs.")
        index = cursor + 1
    return tuple(aces), index


def _parse_acl_flags(text: str) -> Tuple[FrozenSet[str], bool]:
    remaining = text.strip().upper()
    flags = set()
    null_acl = False
    while remaining:
        for token in DACL_FLAG_TOKENS:
            if remaining.startswith(token):
                if token == "NO_ACCESS_CONTROL":
                    null_acl = True
                else:
                    flags.add(token)
                remaining = remaining[len(token):]
                break
        else:
            raise SddlParseError("The ACL has unrecognized flags.")
    return frozenset(flags), null_acl


def parse_sddl(sddl: str) -> SecurityDescriptor:
    """Parse an SDDL security descriptor string into its owner, group and DACL."""
    text = str(sddl or "").strip()
    if not text:
        raise SddlParseError("The security descriptor is empty.")
    if len(text) > MAX_SDDL_LENGTH:
        raise SddlParseError("The security descriptor is too large.")

    owner_sid = ""
    group_sid = ""
    dacl_present = False
    dacl_null = False
    dacl_flags: FrozenSet[str] = frozenset()
    dacl: Tuple[AccessControlEntry, ...] = ()
    seen = set()
    index = 0
    while index < len(text):
        if index + 1 >= len(text) or text[index] not in "OGDS" or text[index + 1] != ":":
            raise SddlParseError("The security descriptor is malformed.")
        tag = text[index]
        if tag in seen:
            raise SddlParseError("The security descriptor repeats a component.")
        seen.add(tag)
        index += 2
        if tag in "OG":
            match = _COMPONENT_PATTERN.search(text, index)
            end = match.start() if match else len(text)
            sid = _resolve_sid_token(text[index:end])
            if tag == "O":
                owner_sid = sid
            else:
                group_sid = sid
            index = end
            continue

        flags_end = index
        while flags_end < len(text) and text[flags_end] != "(" and not _COMPONENT_PATTERN.match(text, flags_end):
            flags_end += 1
        flags, null_acl = _parse_acl_flags(text[index:flags_end])
        ace_texts, index = _split_aces(text, flags_end)
        if index < len(text) and not _COMPONENT_PATTERN.match(text, index):
            raise SddlParseError("The security descriptor is malformed.")
        if tag == "D":
            dacl_present = True
            dacl_null = null_acl
            dacl_flags = flags
            dacl = tuple(_parse_ace(ace_text) for ace_text in ace_texts)
            if dacl_null and dacl:
                raise SddlParseError("A null DACL cannot contain ACEs.")

    return SecurityDescriptor(
        owner_sid=owner_sid,
        group_sid=group_sid,
        dacl_present=dacl_present,
        dacl_null=dacl_null,
        dacl_flags=dacl_flags,
        dacl=dacl,
    )


def _ace_membership(ace: AccessControlEntry, descriptor: SecurityDescriptor, membership: Callable[[str], str]) -> str:
    if ace.sid in (CREATOR_OWNER_SID, CREATOR_GROUP_SID):
        return NOT_MEMBER
    if ace.sid == OWNER_RIGHTS_SID:
        if not descriptor.owner_sid or descriptor.owner_sid == OWNER_RIGHTS_SID:
            return UNKNOWN
        return _checked_membership(descriptor.owner_sid, membership)
    return _checked_membership(ace.sid, membership)


def _checked_membership(sid: str, membership: Callable[[str], str]) -> str:
    try:
        state = membership(sid)
    except Exception:
        return UNKNOWN
    return state if state in (MEMBER, NOT_MEMBER, UNKNOWN) else UNKNOWN


def _uncertain_decision(unresolved: Iterable[str], unsupported: Iterable[str]) -> AccessDecision:
    unresolved_sids = tuple(dict.fromkeys(unresolved))
    unsupported_aces = tuple(dict.fromkeys(unsupported))
    return AccessDecision(
        outcome=OUTCOME_UNVERIFIED,
        reason=REASON_SID_UNRESOLVED if unresolved_sids else REASON_ACL_UNSUPPORTED,
        unresolved_sids=unresolved_sids,
        unsupported_aces=unsupported_aces,
    )


def evaluate_read_access(descriptor: SecurityDescriptor, membership: Callable[[str], str]) -> AccessDecision:
    """Decide whether a principal can read a file's data under its DACL.

    Windows evaluates a DACL in order: the first applicable ACE that names FILE_READ_DATA
    decides. An ACE is uncertain when membership of its principal is unknown, when its type
    is conditional or object-specific, or when it names read only through generic bits. The
    outcome is definite only when every possible resolution of the uncertain ACEs before the
    deciding ACE agrees with it.
    """
    if not descriptor.dacl_present:
        return AccessDecision(OUTCOME_UNVERIFIED, REASON_ACL_MISSING)
    if descriptor.dacl_null:
        return AccessDecision(OUTCOME_ALLOWED, REASON_ACL_NULL_DACL)
    if not descriptor.dacl:
        return AccessDecision(OUTCOME_DENIED, REASON_ACL_EMPTY)

    pending_polarities = []
    unresolved = []
    unsupported = []
    for ace in descriptor.dacl:
        polarity = ACE_POLARITY.get(ace.ace_type)
        if polarity is None or "IO" in ace.flags:
            continue
        names_read = bool(ace.mask & FILE_READ_DATA)
        names_read_generically = bool(ace.mask & GENERIC_RIGHTS_INCLUDING_READ)
        if not names_read and not names_read_generically:
            continue
        state = _ace_membership(ace, descriptor, membership)
        if state == NOT_MEMBER:
            continue
        if state == MEMBER and ace.ace_type in SUPPORTED_ACE_TYPES and names_read:
            if any(pending != polarity for pending in pending_polarities):
                return _uncertain_decision(unresolved, unsupported)
            if polarity == "allow":
                return AccessDecision(OUTCOME_ALLOWED, REASON_ACL_ALLOW)
            return AccessDecision(OUTCOME_DENIED, REASON_ACL_EXPLICIT_DENY)
        pending_polarities.append(polarity)
        if state == UNKNOWN:
            unresolved.append(ace.sid)
        if ace.ace_type not in SUPPORTED_ACE_TYPES:
            unsupported.append(ace.ace_type)
        elif not names_read:
            unsupported.append("generic_rights")

    if "allow" in pending_polarities:
        return _uncertain_decision(unresolved, unsupported)
    return AccessDecision(OUTCOME_DENIED, REASON_ACL_NO_ALLOW)


def evaluate_sddl_read_access(sddl: str, membership: Callable[[str], str]) -> AccessDecision:
    """Parse and evaluate an SDDL string; a descriptor that cannot be parsed is unverified."""
    try:
        descriptor = parse_sddl(sddl)
    except SddlParseError:
        return AccessDecision(OUTCOME_UNVERIFIED, REASON_ACL_PARSE_ERROR)
    return evaluate_read_access(descriptor, membership)


def build_membership(
    principal_sids: Iterable[str],
    *,
    treat_builtin_users_as_member: bool = False,
    resolve_unknown_sid: Optional[Callable[[str], str]] = None,
) -> Callable[[str], str]:
    """Build a membership function for one user from the SIDs they and their groups carry.

    ``resolve_unknown_sid`` may confirm that another principal is not the user (for example
    a directory lookup that finds a different user, or a group whose membership is fully
    known); it can never make the user a member of anything.
    """
    principals = {sid for sid in (normalize_sid(value) for value in principal_sids) if sid}
    user_domains = {domain for domain, _ in (domain_sid_and_rid(sid) for sid in principals) if domain}

    def membership(sid: str) -> str:
        if sid in principals or sid in ALWAYS_MEMBER_SIDS:
            return MEMBER
        if sid == BUILTIN_USERS_SID:
            return MEMBER if treat_builtin_users_as_member else UNKNOWN
        if sid in NEVER_MEMBER_SIDS:
            return NOT_MEMBER
        if sid.startswith("alias:"):
            return NOT_MEMBER if sid[len("alias:"):] in PRIVILEGED_RELATIVE_SID_ALIASES else UNKNOWN
        domain, rid = domain_sid_and_rid(sid)
        if rid in PRIVILEGED_DOMAIN_RIDS:
            return NOT_MEMBER
        if rid == DOMAIN_USERS_RID:
            return MEMBER if domain in user_domains else UNKNOWN
        if resolve_unknown_sid is not None:
            resolved = _checked_membership(sid, resolve_unknown_sid)
            return NOT_MEMBER if resolved == NOT_MEMBER else UNKNOWN
        return UNKNOWN

    return membership
