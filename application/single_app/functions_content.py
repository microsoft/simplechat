# functions_content.py

import bisect
import email.utils
import struct
import zipfile
from xml.etree import ElementTree

import olefile
from bs4 import BeautifulSoup

from functions_debug import debug_print
from config import *
from azure.ai.documentintelligence.models import DocumentAnalysisFeature
from functions_office_media import (
    OFFICE_COMMENT_ANCHOR_MAX_CHARS,
    extract_docx_comments,
    format_word_comments_section,
)
from functions_embeddings import generate_embedding_batch
from functions_embedding_compatibility import active_embedding_profile, embedding_query_slot, read_embedding_settings
from functions_ai_connections import AIConnectionError
import functions_settings
from functions_settings import *
from functions_logging import *
from content_screening.extraction import capture_text_before_chunking


def get_settings(*args, **kwargs):
    return functions_settings.get_settings(*args, **kwargs)

def extract_text_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()

def extract_markdown_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()


def extract_docx_text(file_path, include_comments=True):
    """Extract text from OOXML Word documents such as .docx and .docm."""
    try:
        import docx2txt
    except ImportError as exc:
        raise Exception(
            "docx2txt library is required for .docx/.docm file processing. Install with: pip install docx2txt"
        ) from exc

    body_text = docx2txt.process(file_path) or ""
    if not include_comments:
        return body_text

    comments, _total_words = extract_docx_comments(file_path)
    comments_section = format_word_comments_section(comments)
    if not comments_section:
        return body_text
    if body_text and body_text.strip():
        return f"{body_text.rstrip()}\n\n{comments_section}"
    return comments_section


def _normalize_legacy_doc_text(text):
    """Convert Word control characters into readable plain text."""
    if not text:
        return ""

    field_stripped_text = []
    field_stack = []

    for character in text:
        if character == "\x13":
            field_stack.append("code")
            continue
        if character == "\x14":
            if field_stack:
                field_stack[-1] = "result"
            continue
        if character == "\x15":
            if field_stack:
                field_stack.pop()
            continue

        if not field_stack or field_stack[-1] == "result":
            field_stripped_text.append(character)

    normalized_text = (
        "".join(field_stripped_text)
        .replace("\r", "\n")
        .replace("\x0b", "\n")
        .replace("\x0c", "\n\n")
        .replace("\x07", "\t")
        .replace("\x00", "")
    )
    normalized_text = re.sub(r"[\x01-\x08\x0e-\x1f]", " ", normalized_text)
    normalized_text = re.sub(r"\n{3,}", "\n\n", normalized_text)
    normalized_text = re.sub(r"[ \t]{2,}", " ", normalized_text)
    return normalized_text.strip()


def _score_legacy_doc_candidate(text):
    """Prefer longer candidates with a high ratio of readable characters."""
    if not text:
        return 0

    readable_characters = sum(
        1
        for character in text
        if character.isalnum()
        or character.isspace()
        or character in ".,;:!?()[]{}'\"-_/@#$%^&*+=<>|"
    )
    return readable_characters


def _extract_legacy_doc_raw_text_from_piece_table(word_stream, piece_table_bytes):
    """Parse a PlcPcd piece table and return the un-normalized character stream."""
    if len(piece_table_bytes) < 16 or (len(piece_table_bytes) - 4) % 12 != 0:
        return ""

    piece_count = (len(piece_table_bytes) - 4) // 12
    cp_count = piece_count + 1
    cp_byte_count = cp_count * 4

    if len(piece_table_bytes) != cp_byte_count + (piece_count * 8):
        return ""

    character_positions = struct.unpack(f"<{cp_count}I", piece_table_bytes[:cp_byte_count])
    if any(character_positions[index] > character_positions[index + 1] for index in range(piece_count)):
        return ""

    text_segments = []
    piece_descriptor_offset = cp_byte_count

    for index in range(piece_count):
        start_cp = character_positions[index]
        end_cp = character_positions[index + 1]
        character_count = end_cp - start_cp
        if character_count < 0:
            return ""

        piece_descriptor_start = piece_descriptor_offset + (index * 8)
        piece_descriptor_end = piece_descriptor_start + 8
        piece_descriptor = piece_table_bytes[piece_descriptor_start:piece_descriptor_end]
        if len(piece_descriptor) != 8:
            return ""

        fc_compressed = struct.unpack("<I", piece_descriptor[2:6])[0]
        is_compressed_piece = bool(fc_compressed & 0x40000000)
        stream_offset = fc_compressed & 0x3FFFFFFF

        if is_compressed_piece:
            stream_offset //= 2
            byte_count = character_count
            encoding = "cp1252"
        else:
            byte_count = character_count * 2
            encoding = "utf-16le"

        if stream_offset < 0 or byte_count < 0 or (stream_offset + byte_count) > len(word_stream):
            return ""

        raw_text = word_stream[stream_offset:stream_offset + byte_count]
        text_segments.append(raw_text.decode(encoding, errors='ignore'))

    return "".join(text_segments)


def _extract_legacy_doc_text_from_piece_table(word_stream, piece_table_bytes):
    """Parse a PlcPcd piece table from the WordDocument stream."""
    raw_text = _extract_legacy_doc_raw_text_from_piece_table(word_stream, piece_table_bytes)
    return _normalize_legacy_doc_text(raw_text)


def _extract_legacy_doc_raw_text_from_table_stream(word_stream, table_stream, fc_clx=0, lcb_clx=0):
    """Return the raw un-normalized piece-table text from a Word table stream."""
    if lcb_clx and 0 <= fc_clx and (fc_clx + lcb_clx) <= len(table_stream):
        clx_slice = table_stream[fc_clx:fc_clx + lcb_clx]
        search_offset = 0
        while search_offset <= len(clx_slice) - 5:
            marker_offset = clx_slice.find(b"\x02", search_offset)
            if marker_offset == -1 or marker_offset > len(clx_slice) - 5:
                break
            piece_table_length = struct.unpack("<I", clx_slice[marker_offset + 1:marker_offset + 5])[0]
            piece_table_end = marker_offset + 5 + piece_table_length
            if (
                piece_table_length >= 16
                and (piece_table_length - 4) % 12 == 0
                and piece_table_end <= len(clx_slice)
            ):
                raw_candidate = _extract_legacy_doc_raw_text_from_piece_table(
                    word_stream, clx_slice[marker_offset + 5:piece_table_end]
                )
                if _score_legacy_doc_candidate(_normalize_legacy_doc_text(raw_candidate)) > 0:
                    return raw_candidate
            search_offset = marker_offset + 1

    best_raw = ""
    best_score = 0
    search_offset = 0

    while search_offset <= len(table_stream) - 5:
        piece_table_marker_offset = table_stream.find(b"\x02", search_offset)
        if piece_table_marker_offset == -1 or piece_table_marker_offset > len(table_stream) - 5:
            break

        piece_table_length = struct.unpack(
            "<I",
            table_stream[piece_table_marker_offset + 1:piece_table_marker_offset + 5],
        )[0]
        piece_table_end = piece_table_marker_offset + 5 + piece_table_length

        if (
            piece_table_length >= 16
            and (piece_table_length - 4) % 12 == 0
            and piece_table_end <= len(table_stream)
        ):
            candidate_raw = _extract_legacy_doc_raw_text_from_piece_table(
                word_stream,
                table_stream[piece_table_marker_offset + 5:piece_table_end],
            )
            candidate_score = _score_legacy_doc_candidate(_normalize_legacy_doc_text(candidate_raw))
            if candidate_score > best_score:
                best_raw = candidate_raw
                best_score = candidate_score

        search_offset = piece_table_marker_offset + 1

    return best_raw


def _extract_legacy_doc_text_from_table_stream(word_stream, table_stream):
    """Scan a Word table stream for the most plausible text piece table."""
    best_text = ""
    best_score = 0
    search_offset = 0

    while search_offset <= len(table_stream) - 5:
        piece_table_marker_offset = table_stream.find(b"\x02", search_offset)
        if piece_table_marker_offset == -1 or piece_table_marker_offset > len(table_stream) - 5:
            break

        piece_table_length = struct.unpack(
            "<I",
            table_stream[piece_table_marker_offset + 1:piece_table_marker_offset + 5],
        )[0]
        piece_table_end = piece_table_marker_offset + 5 + piece_table_length

        if (
            piece_table_length >= 16
            and (piece_table_length - 4) % 12 == 0
            and piece_table_end <= len(table_stream)
        ):
            candidate_text = _extract_legacy_doc_text_from_piece_table(
                word_stream,
                table_stream[piece_table_marker_offset + 5:piece_table_end],
            )
            candidate_score = _score_legacy_doc_candidate(candidate_text)
            if candidate_score > best_score:
                best_text = candidate_text
                best_score = candidate_score

        search_offset = piece_table_marker_offset + 1

    return best_text


def _parse_legacy_doc_fib(word_stream):
    """Parse MS-DOC File Information Block (FIB) subdocument lengths and comment table pointers."""
    if not word_stream or len(word_stream) < 154:
        return None

    w_ident = struct.unpack_from("<H", word_stream, 0)[0]
    if w_ident not in (0xA5EC, 0xA5DC):
        return None

    flags = struct.unpack_from("<H", word_stream, 0x0A)[0]
    table_stream_name = "1Table" if (flags & 0x0200) else "0Table"

    csw = struct.unpack_from("<H", word_stream, 0x20)[0]
    offset_cslw = 0x22 + (csw * 2)
    if csw < 14 or offset_cslw + 2 > len(word_stream):
        return None

    cslw = struct.unpack_from("<H", word_stream, offset_cslw)[0]
    offset_rg_lw = offset_cslw + 2
    if cslw < 11 or offset_rg_lw + (cslw * 4) > len(word_stream):
        return None

    (
        ccp_text,
        ccp_ftn,
        ccp_hdr,
        ccp_mcr,
        ccp_atn,
        ccp_edn,
        ccp_txbx,
        ccp_hdr_txbx,
    ) = struct.unpack_from("<8I", word_stream, offset_rg_lw + 12)

    offset_cb_fc_lcb = offset_rg_lw + (cslw * 4)
    cb_rg_fc_lcb = 0
    offset_fc_lcb = offset_cb_fc_lcb + 2
    if offset_fc_lcb <= len(word_stream):
        cb_rg_fc_lcb = struct.unpack_from("<H", word_stream, offset_cb_fc_lcb)[0]

    def _read_fc_lcb(entry_index):
        entry_offset = offset_fc_lcb + (entry_index * 8)
        if entry_index < cb_rg_fc_lcb and (entry_offset + 8) <= len(word_stream):
            return struct.unpack_from("<II", word_stream, entry_offset)
        return (0, 0)

    fc_plcfand_ref, lcb_plcfand_ref = _read_fc_lcb(4)
    fc_plcfand_txt, lcb_plcfand_txt = _read_fc_lcb(5)
    fc_plcfbte_chpx, lcb_plcfbte_chpx = _read_fc_lcb(12)
    fc_sttbf_ffn, lcb_sttbf_ffn = _read_fc_lcb(15)
    fc_clx, lcb_clx = _read_fc_lcb(33)
    fc_grp_xst_atn_owners, lcb_grp_xst_atn_owners = _read_fc_lcb(36)
    fc_plcfbkf_atn, lcb_plcfbkf_atn = _read_fc_lcb(42)
    fc_plcfbkl_atn, lcb_plcfbkl_atn = _read_fc_lcb(43)

    return {
        "table_stream_name": table_stream_name,
        "ccp_text": ccp_text,
        "ccp_ftn": ccp_ftn,
        "ccp_hdr": ccp_hdr,
        "ccp_mcr": ccp_mcr,
        "ccp_atn": ccp_atn,
        "ccp_edn": ccp_edn,
        "ccp_txbx": ccp_txbx,
        "ccp_hdr_txbx": ccp_hdr_txbx,
        "fc_plcfand_ref": fc_plcfand_ref,
        "lcb_plcfand_ref": lcb_plcfand_ref,
        "fc_plcfand_txt": fc_plcfand_txt,
        "lcb_plcfand_txt": lcb_plcfand_txt,
        "fc_plcfbte_chpx": fc_plcfbte_chpx,
        "lcb_plcfbte_chpx": lcb_plcfbte_chpx,
        "fc_sttbf_ffn": fc_sttbf_ffn,
        "lcb_sttbf_ffn": lcb_sttbf_ffn,
        "fc_clx": fc_clx,
        "lcb_clx": lcb_clx,
        "fc_grp_xst_atn_owners": fc_grp_xst_atn_owners,
        "lcb_grp_xst_atn_owners": lcb_grp_xst_atn_owners,
        "fc_plcfbkf_atn": fc_plcfbkf_atn,
        "lcb_plcfbkf_atn": lcb_plcfbkf_atn,
        "fc_plcfbkl_atn": fc_plcfbkl_atn,
        "lcb_plcfbkl_atn": lcb_plcfbkl_atn,
    }


def _parse_legacy_doc_atn_owners(table_stream, fc_owners, lcb_owners):
    """Parse GrpXstAtnOwners array of UTF-16LE length-prefixed author names."""
    owners = []
    if not lcb_owners or fc_owners < 0 or (fc_owners + lcb_owners) > len(table_stream):
        return owners

    owners_bytes = table_stream[fc_owners:fc_owners + lcb_owners]
    offset = 0
    while offset + 2 <= len(owners_bytes):
        cch = struct.unpack_from("<H", owners_bytes, offset)[0]
        offset += 2
        byte_len = cch * 2
        if offset + byte_len > len(owners_bytes):
            break
        owner_name = owners_bytes[offset:offset + byte_len].decode("utf-16le", errors="ignore").strip("\x00").strip()
        owners.append(owner_name)
        offset += byte_len
    return owners


def _parse_legacy_doc_atn_bookmarks(table_stream, fib):
    """Parse PlcfbkfAtn and PlcfbklAtn to map bookmark indices to (start_cp, end_cp) in body text."""
    fc_bkf = fib.get("fc_plcfbkf_atn", 0)
    lcb_bkf = fib.get("lcb_plcfbkf_atn", 0)
    fc_bkl = fib.get("fc_plcfbkl_atn", 0)
    lcb_bkl = fib.get("lcb_plcfbkl_atn", 0)
    if (
        lcb_bkf < 8
        or (lcb_bkf - 4) % 8 != 0
        or (fc_bkf + lcb_bkf) > len(table_stream)
        or lcb_bkl < 8
        or lcb_bkl % 4 != 0
        or (fc_bkl + lcb_bkl) > len(table_stream)
    ):
        return {}

    bkf_bytes = table_stream[fc_bkf:fc_bkf + lcb_bkf]
    bkl_bytes = table_stream[fc_bkl:fc_bkl + lcb_bkl]
    bkf_count = (lcb_bkf - 4) // 8
    bkl_count = (lcb_bkl // 4) - 1
    if bkf_count <= 0 or bkl_count <= 0:
        return {}

    start_cps = struct.unpack_from(f"<{bkf_count + 1}I", bkf_bytes, 0)
    end_cps = struct.unpack_from(f"<{bkl_count + 1}I", bkl_bytes, 0)
    fbkf_offset = (bkf_count + 1) * 4

    bookmark_ranges = {}
    for idx in range(bkf_count):
        ibkl = struct.unpack_from("<H", bkf_bytes, fbkf_offset + (idx * 4))[0]
        if 0 <= ibkl < bkl_count:
            start_cp = start_cps[idx]
            end_cp = end_cps[ibkl]
            if end_cp >= start_cp:
                bookmark_ranges[idx] = (start_cp, end_cp)
    return bookmark_ranges


def _extract_legacy_doc_comments_from_streams(table_stream, fib, raw_full_text):
    """Extract structured comments and total body word count from decoded MS-DOC streams."""
    if not fib or not raw_full_text:
        return [], len(_normalize_legacy_doc_text(raw_full_text).split())

    ccp_text = fib.get("ccp_text", 0)
    ccp_atn = fib.get("ccp_atn", 0)
    body_raw = raw_full_text[:ccp_text] if ccp_text > 0 else raw_full_text
    total_body_words = len(_normalize_legacy_doc_text(body_raw).split())

    if ccp_atn <= 0:
        return [], total_body_words

    atn_start = (
        ccp_text
        + fib.get("ccp_ftn", 0)
        + fib.get("ccp_hdr", 0)
        + fib.get("ccp_mcr", 0)
    )
    atn_end = atn_start + ccp_atn
    if atn_start >= len(raw_full_text):
        return [], total_body_words

    raw_atn_text = raw_full_text[atn_start:min(atn_end, len(raw_full_text))]
    if not raw_atn_text:
        return [], total_body_words

    owners = _parse_legacy_doc_atn_owners(
        table_stream,
        fib.get("fc_grp_xst_atn_owners", 0),
        fib.get("lcb_grp_xst_atn_owners", 0),
    )
    bookmark_ranges = _parse_legacy_doc_atn_bookmarks(table_stream, fib)

    # Parse PlcfandRef (30-byte ATRDPre10 per annotation reference)
    ref_records = []
    fc_ref = fib.get("fc_plcfand_ref", 0)
    lcb_ref = fib.get("lcb_plcfand_ref", 0)
    if lcb_ref >= 38 and (lcb_ref - 4) % 34 == 0 and (fc_ref + lcb_ref) <= len(table_stream):
        ref_bytes = table_stream[fc_ref:fc_ref + lcb_ref]
        ref_count = (lcb_ref - 4) // 34
        ref_cps = struct.unpack_from(f"<{ref_count + 1}I", ref_bytes, 0)
        atrd_base = (ref_count + 1) * 4
        for idx in range(ref_count):
            atrd = ref_bytes[atrd_base + (idx * 30):atrd_base + ((idx + 1) * 30)]
            initl_cch = min(struct.unpack_from("<H", atrd, 0)[0], 9)
            initials = atrd[2:2 + (initl_cch * 2)].decode("utf-16le", errors="ignore").strip("\x00").strip()
            ibst = struct.unpack_from("<H", atrd, 20)[0]
            author = owners[ibst] if 0 <= ibst < len(owners) else ""
            bkmk_tag = struct.unpack_from("<i", atrd, 26)[0]
            ref_records.append({
                "anchor_cp": ref_cps[idx],
                "author": author,
                "initials": initials,
                "bkmk_tag": bkmk_tag,
            })

    # Parse PlcfandTxt (start/end CP offsets within the annotation subdocument)
    comment_slices = []
    fc_txt = fib.get("fc_plcfand_txt", 0)
    lcb_txt = fib.get("lcb_plcfand_txt", 0)
    if lcb_txt >= 8 and lcb_txt % 4 == 0 and (fc_txt + lcb_txt) <= len(table_stream):
        txt_bytes = table_stream[fc_txt:fc_txt + lcb_txt]
        cp_count = lcb_txt // 4
        txt_cps = struct.unpack_from(f"<{cp_count}I", txt_bytes, 0)
        for idx in range(cp_count - 1):
            start_offset = max(0, min(txt_cps[idx], len(raw_atn_text)))
            end_offset = max(start_offset, min(txt_cps[idx + 1], len(raw_atn_text)))
            if end_offset > start_offset:
                comment_slices.append(raw_atn_text[start_offset:end_offset])

    if not comment_slices:
        if "\x05" in raw_atn_text:
            comment_slices = [part for part in raw_atn_text.split("\x05") if part.strip()]
        else:
            comment_slices = [raw_atn_text]

    comments = []
    for idx, raw_slice in enumerate(comment_slices):
        comment_text = _normalize_legacy_doc_text(raw_slice)
        if not comment_text:
            continue

        ref_info = ref_records[idx] if idx < len(ref_records) else {}
        author = ref_info.get("author") or (owners[0] if len(owners) == 1 else "")
        initials = ref_info.get("initials", "")
        anchor_cp = ref_info.get("anchor_cp")
        bkmk_tag = ref_info.get("bkmk_tag", -1)

        word_offset = None
        anchor_text = ""
        if anchor_cp is not None and ccp_text > 0:
            bounded_cp = max(0, min(int(anchor_cp), len(body_raw)))
            body_prefix = _normalize_legacy_doc_text(body_raw[:bounded_cp])
            word_offset = len(body_prefix.split())

            if bkmk_tag in bookmark_ranges:
                bkmk_start, bkmk_end = bookmark_ranges[bkmk_tag]
                anchor_text = _normalize_legacy_doc_text(
                    body_raw[max(0, bkmk_start):min(len(body_raw), bkmk_end)]
                )[:OFFICE_COMMENT_ANCHOR_MAX_CHARS]
            elif bounded_cp > 0:
                para_start = body_raw.rfind("\r", 0, bounded_cp)
                snippet_start = max(0 if para_start == -1 else para_start + 1, bounded_cp - 120)
                anchor_text = _normalize_legacy_doc_text(
                    body_raw[snippet_start:bounded_cp]
                )[:OFFICE_COMMENT_ANCHOR_MAX_CHARS]

        comments.append({
            "id": str(idx + 1),
            "author": author,
            "initials": initials,
            "date": "",
            "text": comment_text,
            "anchor_text": anchor_text,
            "word_offset": word_offset,
            "position_known": word_offset is not None,
            "parent_id": None,
            "done": False,
            "replies": [],
        })

    return comments, total_body_words


LEGACY_DOC_FKP_PAGE_SIZE = 512
LEGACY_DOC_MAX_CHPX_PAGES = 4096
LEGACY_DOC_MAX_STYLE_RUNS = 100000
LEGACY_DOC_ICO_COLORS = {
    1: "#000000", 2: "#0000FF", 3: "#00FFFF", 4: "#00FF00", 5: "#FF00FF", 6: "#FF0000",
    7: "#FFFF00", 8: "#FFFFFF", 9: "#000080", 10: "#008080", 11: "#008000", 12: "#800080",
    13: "#800000", 14: "#808000", 15: "#808080", 16: "#C0C0C0",
}


def _legacy_doc_piece_map(table_stream, fib):
    """Return ``[(start_cp, end_cp, byte_start, is_compressed)]`` sorted by byte offset."""
    fc_clx = fib.get("fc_clx", 0)
    lcb_clx = fib.get("lcb_clx", 0)
    if not lcb_clx or fc_clx < 0 or fc_clx + lcb_clx > len(table_stream):
        return []

    clx = table_stream[fc_clx:fc_clx + lcb_clx]
    offset = 0
    while offset < len(clx) and clx[offset] == 0x01:
        if offset + 3 > len(clx):
            return []
        offset += 3 + struct.unpack_from("<H", clx, offset + 1)[0]
    if offset + 5 > len(clx) or clx[offset] != 0x02:
        return []

    plc_length = struct.unpack_from("<I", clx, offset + 1)[0]
    plc = clx[offset + 5:offset + 5 + plc_length]
    if len(plc) < 16 or (len(plc) - 4) % 12 != 0:
        return []

    piece_count = (len(plc) - 4) // 12
    cps = struct.unpack_from(f"<{piece_count + 1}I", plc, 0)
    pieces = []
    for index in range(piece_count):
        fc_compressed = struct.unpack_from("<I", plc, ((piece_count + 1) * 4) + (index * 8) + 2)[0]
        is_compressed = bool(fc_compressed & 0x40000000)
        byte_start = fc_compressed & 0x3FFFFFFF
        if is_compressed:
            byte_start //= 2
        pieces.append((cps[index], cps[index + 1], byte_start, is_compressed))
    pieces.sort(key=lambda piece: piece[2])
    return pieces


def _legacy_doc_fc_range_to_cp_ranges(pieces, piece_starts, fc_start, fc_end):
    """Map a WordDocument byte range onto character-position ranges through the piece table."""
    ranges = []
    index = max(bisect.bisect_right(piece_starts, fc_start) - 1, 0)
    while index < len(pieces):
        start_cp, end_cp, byte_start, is_compressed = pieces[index]
        if byte_start >= fc_end:
            break
        unit = 1 if is_compressed else 2
        byte_end = byte_start + ((end_cp - start_cp) * unit)
        low = max(fc_start, byte_start)
        high = min(fc_end, byte_end)
        if low < high:
            ranges.append((
                start_cp + ((low - byte_start) // unit),
                start_cp + ((high - byte_start) // unit),
            ))
        index += 1
    return ranges


def _parse_legacy_doc_chp_sprms(grpprl):
    """Decode the character-formatting SPRMs this extractor understands from a CHPX Grpprl."""
    props = {}
    position = 0
    while position + 2 <= len(grpprl):
        opcode = struct.unpack_from("<H", grpprl, position)[0]
        position += 2
        spra = opcode >> 13
        if spra in (0, 1):
            operand_size = 1
        elif spra in (2, 4, 5):
            operand_size = 2
        elif spra == 3:
            operand_size = 4
        elif spra == 7:
            operand_size = 3
        elif spra == 6 and position < len(grpprl):
            operand_size = grpprl[position] + 1
        else:
            break
        operand = grpprl[position:position + operand_size]
        if len(operand) < operand_size:
            break
        position += operand_size

        if opcode == 0x4A43:
            props["size_pt"] = struct.unpack("<H", operand)[0] / 2.0
        elif opcode == 0x4A4F:
            props["font_index"] = struct.unpack("<H", operand)[0]
        elif opcode == 0x0835 and operand[0] in (0, 1):
            props["bold"] = bool(operand[0])
        elif opcode == 0x0836 and operand[0] in (0, 1):
            props["italic"] = bool(operand[0])
        elif opcode == 0x2A3E:
            props["underline"] = operand[0] != 0
        elif opcode == 0x2A42 and operand[0] in LEGACY_DOC_ICO_COLORS:
            props["color"] = LEGACY_DOC_ICO_COLORS[operand[0]]
        elif opcode == 0x6870 and operand[3] != 0xFF:
            props["color"] = f"#{operand[0]:02X}{operand[1]:02X}{operand[2]:02X}"
    return props


def _parse_legacy_doc_font_table(table_stream, fc_sttbf_ffn, lcb_sttbf_ffn):
    """Return the font names from the SttbfFfn font table, indexed by font number."""
    if not lcb_sttbf_ffn or fc_sttbf_ffn < 0 or fc_sttbf_ffn + lcb_sttbf_ffn > len(table_stream):
        return []
    data = table_stream[fc_sttbf_ffn:fc_sttbf_ffn + lcb_sttbf_ffn]
    if len(data) < 4:
        return []
    count = struct.unpack_from("<H", data, 0)[0]

    for header_size in (4, 2):
        position = header_size
        names = []
        for _ in range(count):
            if position >= len(data):
                names = None
                break
            entry_end = position + 1 + data[position]
            if data[position] < 40 or entry_end > len(data):
                names = None
                break
            raw_name = data[position + 40:entry_end]
            names.append(raw_name.decode("utf-16le", errors="ignore").split("\x00")[0].strip())
            position = entry_end
        if names is not None:
            return names
    return []


def _legacy_doc_chpx_runs(word_stream, table_stream, fib):
    """Yield ``(fc_first, fc_last, props)`` for every character-formatting run in the CHPX bin table."""
    fc_bte = fib.get("fc_plcfbte_chpx", 0)
    lcb_bte = fib.get("lcb_plcfbte_chpx", 0)
    if not lcb_bte or fc_bte < 0 or fc_bte + lcb_bte > len(table_stream) or lcb_bte < 12:
        return
    plc = table_stream[fc_bte:fc_bte + lcb_bte]
    page_count = min((len(plc) - 4) // 8, LEGACY_DOC_MAX_CHPX_PAGES)
    for index in range(page_count):
        page_number = struct.unpack_from("<I", plc, ((page_count + 1) * 4) + (index * 4))[0] & 0x3FFFFF
        page_start = page_number * LEGACY_DOC_FKP_PAGE_SIZE
        page = word_stream[page_start:page_start + LEGACY_DOC_FKP_PAGE_SIZE]
        if len(page) < LEGACY_DOC_FKP_PAGE_SIZE:
            continue
        run_count = page[LEGACY_DOC_FKP_PAGE_SIZE - 1]
        offsets_start = 4 * (run_count + 1)
        if run_count == 0 or offsets_start + run_count > LEGACY_DOC_FKP_PAGE_SIZE - 1:
            continue
        boundaries = struct.unpack_from(f"<{run_count + 1}I", page, 0)
        for run_index in range(run_count):
            props = {}
            chpx_offset = page[offsets_start + run_index] * 2
            if chpx_offset and chpx_offset < LEGACY_DOC_FKP_PAGE_SIZE - 1:
                cb = page[chpx_offset]
                props = _parse_legacy_doc_chp_sprms(page[chpx_offset + 1:chpx_offset + 1 + cb])
            yield boundaries[run_index], boundaries[run_index + 1], props


def extract_legacy_doc_character_runs(file_path):
    """Best-effort character formatting runs from a legacy OLE .doc file.

    Reads direct run properties (font, size, bold, italic, underline, colour) from the CHPX bin table
    and maps them onto body text through the piece table. Paragraph/character style inheritance and
    document defaults are not applied, so values a run does not set directly stay ``None``.
    Returns ``None`` when the structures cannot be read, otherwise
    ``{'runs': [...], 'total_body_words': int, 'notes': [...]}``.
    """
    if not file_path or not olefile.isOleFile(file_path):
        return None

    ole = olefile.OleFileIO(file_path)
    try:
        if not ole.exists("WordDocument"):
            return None
        word_stream = ole.openstream("WordDocument").read()
        fib = _parse_legacy_doc_fib(word_stream)
        if not fib:
            return None

        preferred_table = fib.get("table_stream_name", "1Table")
        for table_stream_name in [preferred_table] + [n for n in ("1Table", "0Table") if n != preferred_table]:
            if not ole.exists(table_stream_name):
                continue
            table_stream = ole.openstream(table_stream_name).read()
            raw_text = _extract_legacy_doc_raw_text_from_table_stream(
                word_stream, table_stream, fc_clx=fib.get("fc_clx", 0), lcb_clx=fib.get("lcb_clx", 0)
            )
            pieces = _legacy_doc_piece_map(table_stream, fib)
            if raw_text and pieces:
                break
        else:
            return None

        body_length = fib.get("ccp_text", 0) or len(raw_text)
        body_text = raw_text[:body_length]
        word_starts = [match.start() for match in re.finditer(r"\S+", body_text)]
        font_names = _parse_legacy_doc_font_table(
            table_stream, fib.get("fc_sttbf_ffn", 0), fib.get("lcb_sttbf_ffn", 0)
        )
        piece_starts = [piece[2] for piece in pieces]

        runs = []
        for fc_first, fc_last, props in _legacy_doc_chpx_runs(word_stream, table_stream, fib):
            for start_cp, end_cp in _legacy_doc_fc_range_to_cp_ranges(pieces, piece_starts, fc_first, fc_last):
                if start_cp >= len(body_text):
                    continue
                text = re.sub(r"[\x00-\x08\x0b-\x1f]", " ", body_text[start_cp:min(end_cp, len(body_text))])
                if not text.strip():
                    continue
                font_index = props.get("font_index")
                runs.append({
                    "word_offset": bisect.bisect_left(word_starts, start_cp),
                    "text": text,
                    "font": font_names[font_index] if font_index is not None and font_index < len(font_names) else None,
                    "size_pt": props.get("size_pt"),
                    "color": props.get("color"),
                    "bold": props.get("bold", False),
                    "italic": props.get("italic", False),
                    "underline": props.get("underline", False),
                })
                if len(runs) >= LEGACY_DOC_MAX_STYLE_RUNS:
                    break
            if len(runs) >= LEGACY_DOC_MAX_STYLE_RUNS:
                break

        notes = [
            "Legacy .doc formatting is best effort: only direct run properties are read. Paragraph and "
            "character style inheritance and document defaults are not applied, so text that relies on "
            "styles for its font or size is reported as unresolved.",
        ]
        if len(runs) >= LEGACY_DOC_MAX_STYLE_RUNS:
            notes.append(f"Only the first {LEGACY_DOC_MAX_STYLE_RUNS} formatting runs were read.")
        return {"runs": runs, "total_body_words": len(word_starts), "notes": notes}
    except Exception:
        return None
    finally:
        ole.close()


def extract_legacy_doc_comments(file_path):
    """Extract structured comments and total body word count from a legacy OLE .doc file."""
    if not file_path or not olefile.isOleFile(file_path):
        return [], 0

    ole = olefile.OleFileIO(file_path)
    try:
        if not ole.exists("WordDocument"):
            return [], 0

        word_stream = ole.openstream("WordDocument").read()
        fib = _parse_legacy_doc_fib(word_stream)
        if not fib:
            return [], 0

        preferred_table = fib.get("table_stream_name", "1Table")
        table_candidates = [preferred_table] + [
            name for name in ("1Table", "0Table") if name != preferred_table
        ]
        for table_stream_name in table_candidates:
            if not ole.exists(table_stream_name):
                continue
            table_stream = ole.openstream(table_stream_name).read()
            raw_full_text = _extract_legacy_doc_raw_text_from_table_stream(
                word_stream,
                table_stream,
                fc_clx=fib.get("fc_clx", 0),
                lcb_clx=fib.get("lcb_clx", 0),
            )
            if not raw_full_text:
                continue
            return _extract_legacy_doc_comments_from_streams(table_stream, fib, raw_full_text)

        return [], 0
    except Exception:
        return [], 0
    finally:
        ole.close()


def extract_word_comments(file_path, file_extension=None):
    """Extract structured review comments and total body words from any supported Word file."""
    resolved_extension = (file_extension or os.path.splitext(str(file_path or ""))[1]).lower()
    if resolved_extension == ".doc" and olefile.isOleFile(file_path):
        return extract_legacy_doc_comments(file_path)
    if zipfile.is_zipfile(file_path):
        return extract_docx_comments(file_path)
    return [], 0


def extract_legacy_doc_text(file_path, include_comments=True):
    """Extract text from Word 97-2003 .doc files using OLE streams and piece tables."""
    if not olefile.isOleFile(file_path):
        raise Exception("File is not a valid OLE compound document")

    ole = olefile.OleFileIO(file_path)
    try:
        if not ole.exists("WordDocument"):
            raise Exception("Missing WordDocument stream")

        word_stream = ole.openstream("WordDocument").read()
        fib = _parse_legacy_doc_fib(word_stream)

        best_text = ""
        best_score = 0
        best_raw = ""
        best_table_stream = b""

        for table_stream_name in ("1Table", "0Table"):
            if not ole.exists(table_stream_name):
                continue

            table_stream = ole.openstream(table_stream_name).read()
            candidate_raw = _extract_legacy_doc_raw_text_from_table_stream(
                word_stream,
                table_stream,
                fc_clx=fib.get("fc_clx", 0) if fib else 0,
                lcb_clx=fib.get("lcb_clx", 0) if fib else 0,
            )
            candidate_text = _normalize_legacy_doc_text(candidate_raw)
            candidate_score = _score_legacy_doc_candidate(candidate_text)
            if candidate_score > best_score:
                best_text = candidate_text
                best_score = candidate_score
                best_raw = candidate_raw
                best_table_stream = table_stream

        if not best_text:
            raise Exception("Could not locate a readable text piece table in the document")

        if fib and fib.get("ccp_atn", 0) > 0 and best_raw:
            atn_start = (
                fib.get("ccp_text", 0)
                + fib.get("ccp_ftn", 0)
                + fib.get("ccp_hdr", 0)
                + fib.get("ccp_mcr", 0)
            )
            atn_end = atn_start + fib.get("ccp_atn", 0)
            if 0 <= atn_start < len(best_raw):
                non_atn_raw = best_raw[:atn_start] + best_raw[min(atn_end, len(best_raw)):]
                body_text = _normalize_legacy_doc_text(non_atn_raw)
            else:
                body_text = best_text

            if not include_comments:
                return body_text

            comments, _total_words = _extract_legacy_doc_comments_from_streams(
                best_table_stream, fib, best_raw
            )
            comments_section = format_word_comments_section(comments)
            if comments_section:
                if body_text:
                    return f"{body_text}\n\n{comments_section}"
                return comments_section
            return body_text

        return best_text
    finally:
        ole.close()


def _normalize_msg_text(text):
    """Normalize Outlook message text into readable plain text."""
    if not text:
        return ""

    normalized_text = (
        str(text)
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\x00", "")
    )
    normalized_text = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f]", " ", normalized_text)
    normalized_text = re.sub(r"[ \t]{2,}", " ", normalized_text)
    normalized_text = re.sub(r"\n{3,}", "\n\n", normalized_text)
    return normalized_text.strip()


def _build_msg_stream_map(ole):
    """Build a map of top-level MAPI property streams from an Outlook .msg file."""
    stream_map = {}
    for stream_entry in ole.listdir(streams=True, storages=False):
        if not stream_entry or len(stream_entry) != 1:
            continue

        stream_name = stream_entry[-1]
        normalized_stream_name = str(stream_name or "").upper()
        if normalized_stream_name.startswith("__SUBSTG1.0_"):
            stream_map[normalized_stream_name] = stream_entry

    return stream_map


def _decode_msg_string(data, encoding):
    """Decode a MAPI string property stream."""
    if not data:
        return ""

    try:
        return _normalize_msg_text(data.decode(encoding, errors="ignore"))
    except Exception:
        return ""


def _extract_msg_string_property(ole, stream_map, property_id):
    """Extract a Unicode or ANSI string MAPI property by hex property id."""
    normalized_property_id = str(property_id or "").upper().zfill(4)
    for type_suffix, encoding in (("001F", "utf-16le"), ("001E", "cp1252")):
        stream_entry = stream_map.get(f"__SUBSTG1.0_{normalized_property_id}{type_suffix}")
        if not stream_entry:
            continue

        value = _decode_msg_string(ole.openstream(stream_entry).read(), encoding)
        if value:
            return value

    return ""


def _extract_msg_first_string_property(ole, stream_map, property_ids):
    """Return the first readable MAPI string property from a list of ids."""
    for property_id in property_ids:
        value = _extract_msg_string_property(ole, stream_map, property_id)
        if value:
            return value

    return ""


def _decode_msg_html_bytes(html_bytes):
    """Decode and strip HTML body content from a MAPI HTML body stream."""
    if not html_bytes:
        return ""

    encodings = []
    if html_bytes.startswith((b"\xff\xfe", b"\xfe\xff")) or html_bytes.count(b"\x00") > max(2, len(html_bytes) // 5):
        encodings.append("utf-16le")
    encodings.extend(["utf-8-sig", "cp1252"])

    decoded_html = ""
    for encoding in encodings:
        try:
            candidate_html = html_bytes.decode(encoding, errors="replace")
        except Exception:
            continue

        if candidate_html and (not decoded_html or candidate_html.count("\ufffd") < decoded_html.count("\ufffd")):
            decoded_html = candidate_html

    if not decoded_html:
        return ""

    soup = BeautifulSoup(decoded_html, "html.parser")
    for unsafe_node in soup(["script", "style"]):
        unsafe_node.decompose()
    return _normalize_msg_text(soup.get_text(separator=" ", strip=True))


def _extract_msg_html_body(ole, stream_map):
    """Extract plain text from the Outlook HTML body MAPI property."""
    html_string = _extract_msg_string_property(ole, stream_map, "1013")
    if html_string:
        soup = BeautifulSoup(html_string, "html.parser")
        for unsafe_node in soup(["script", "style"]):
            unsafe_node.decompose()
        return _normalize_msg_text(soup.get_text(separator=" ", strip=True))

    stream_entry = stream_map.get("__SUBSTG1.0_10130102")
    if not stream_entry:
        return ""

    return _decode_msg_html_bytes(ole.openstream(stream_entry).read())


def _format_msg_sender(sender_name, sender_email):
    """Format sender metadata without duplicating values."""
    normalized_name = _normalize_msg_text(sender_name)
    normalized_email = _normalize_msg_text(sender_email)
    if normalized_name and normalized_email and normalized_email.lower() not in normalized_name.lower():
        return f"{normalized_name} <{normalized_email}>"
    return normalized_name or normalized_email


def extract_outlook_msg_text(file_path):
    """Extract searchable plain text from an Outlook .msg file."""
    if not olefile.isOleFile(file_path):
        raise Exception("File is not a valid Outlook .msg OLE document")

    ole = olefile.OleFileIO(file_path)
    try:
        stream_map = _build_msg_stream_map(ole)
        if not stream_map:
            raise Exception("No readable Outlook message property streams found")

        subject = _extract_msg_first_string_property(ole, stream_map, ["0037"])
        sender = _format_msg_sender(
            _extract_msg_first_string_property(ole, stream_map, ["0C1A", "0042"]),
            _extract_msg_first_string_property(ole, stream_map, ["0C1F", "0065"]),
        )
        display_to = _extract_msg_first_string_property(ole, stream_map, ["0E04"])
        display_cc = _extract_msg_first_string_property(ole, stream_map, ["0E03"])
        message_id = _extract_msg_first_string_property(ole, stream_map, ["1035"])
        body_text = _extract_msg_first_string_property(ole, stream_map, ["1000"])
        if not body_text:
            body_text = _extract_msg_html_body(ole, stream_map)

        header_lines = []
        for label, value in (
            ("Subject", subject),
            ("From", sender),
            ("To", display_to),
            ("Cc", display_cc),
            ("Message-Id", message_id),
        ):
            if value:
                header_lines.append(f"{label}: {value}")

        message_parts = []
        if header_lines:
            message_parts.append("\n".join(header_lines))
        if body_text:
            message_parts.append(f"Body:\n{body_text}")

        extracted_text = _normalize_msg_text("\n\n".join(message_parts))
        if not extracted_text:
            raise Exception("No readable text content found in Outlook message")

        return extracted_text
    finally:
        ole.close()

_SELECTION_MARK_PATTERN = re.compile(r'(\u2612|\u2610|:selected:|:unselected:)', re.IGNORECASE)


def _clean_selection_mark_label(label_text):
    """Return a compact text label adjacent to a DI selection mark."""
    clean_label = re.sub(r'<[^>]+>', ' ', str(label_text or ''))
    clean_label = re.sub(r'\s+', ' ', clean_label).strip(' -:\t')
    if len(clean_label) > 240:
        clean_label = clean_label[:240].rstrip()
    return clean_label


def _build_selection_mark_summary(page_text):
    """Build explicit checked/unchecked text from Layout markdown selection marks."""
    summaries = []
    seen = set()

    for raw_line in str(page_text or '').splitlines():
        if not _SELECTION_MARK_PATTERN.search(raw_line):
            continue

        parts = _SELECTION_MARK_PATTERN.split(raw_line)
        for index in range(1, len(parts), 2):
            marker = parts[index].lower()
            label = _clean_selection_mark_label(parts[index + 1] if index + 1 < len(parts) else '')
            if not label and index > 1:
                label = _clean_selection_mark_label(parts[index - 1])
            if not label:
                continue

            state = 'unchecked'
            if marker in ('\u2612', ':selected:'):
                state = 'checked'

            summary_key = (label.lower(), state)
            if summary_key in seen:
                continue
            seen.add(summary_key)
            summaries.append(f"- {label}: {state}")

    if not summaries:
        return ''

    return "Selection marks detected:\n" + "\n".join(summaries)


def _append_selection_mark_summary(page_text):
    """Append explicit selection-mark language to Layout content when available."""
    summary = _build_selection_mark_summary(page_text)
    if not summary:
        return page_text
    return f"{str(page_text or '').rstrip()}\n\n{summary}"


def extract_content_with_azure_di(file_path, extraction_mode='read', pages=None):
    """
    Extracts text page-by-page using Azure Document Intelligence.
    and returns a list of dicts, each containing page_number and content.
    """
    try:
        document_intelligence_client = CLIENTS['document_intelligence_client'] # Ensure CLIENTS is populated
        normalized_extraction_mode = functions_settings.normalize_document_intelligence_pdf_image_extraction_mode(extraction_mode)
        model_id = "prebuilt-layout" if normalized_extraction_mode == "layout" else "prebuilt-read"
        analyze_options = {}
        if normalized_extraction_mode == "layout":
            analyze_options["output_content_format"] = "markdown"
        if pages:
            analyze_options["pages"] = str(pages)

        # Formula extraction is a billed Document Intelligence add-on, so it is opt-in and only
        # applies to Layout, which is the model that supports it.
        if normalized_extraction_mode == "layout" and functions_settings.is_document_intelligence_formula_extraction_enabled():
            analyze_options["features"] = [DocumentAnalysisFeature.FORMULAS]
        
        # Debug logging for troubleshooting
        debug_print(f"Starting Azure DI extraction for: {os.path.basename(file_path)}")
        debug_print(f"AZURE_ENVIRONMENT: {AZURE_ENVIRONMENT}")
        debug_print(f"Azure DI extraction mode: {normalized_extraction_mode}")
        if pages:
            debug_print(f"Azure DI page selection: {pages}")

        if AZURE_ENVIRONMENT in ("usgovernment", "custom"):
            # Required format for Document Intelligence API version 2024-11-30
            debug_print("Using US Government/Custom environment with base64Source")
            with open(file_path, 'rb') as f:
                file_bytes = f.read()
                base64_source = base64.b64encode(file_bytes).decode('utf-8')
            
            # For stable API 1.0.2, use the correct body parameter structure
            analyze_request = {"base64Source": base64_source}
            poller = document_intelligence_client.begin_analyze_document(
                model_id=model_id,
                body=analyze_request,
                **analyze_options
            )
            debug_print("Successfully started analysis with base64Source")
        else:
            debug_print("Using Public cloud environment")
            with open(file_path, 'rb') as f:
                # For stable API 1.0.2, the file needs to be passed as part of the body
                file_content = f.read()
                
                # Try different approaches for the stable API
                try:
                    # Method 1: Use bytes directly in body
                    poller = document_intelligence_client.begin_analyze_document(
                        model_id=model_id,
                        body=file_content,
                        content_type="application/pdf",
                        **analyze_options
                    )
                    debug_print("Successfully started analysis with body as bytes")
                except Exception as e1:
                    debug_print(f"Method 1 failed: {e1}")
                    
                    try:
                        # Method 2: Use base64 format for consistency
                        base64_source = base64.b64encode(file_content).decode('utf-8')
                        analyze_request = {"base64Source": base64_source}
                        poller = document_intelligence_client.begin_analyze_document(
                            model_id=model_id,
                            body=analyze_request,
                            **analyze_options
                        )
                        debug_print("Successfully started analysis with base64Source in body")
                    except Exception as e2:
                        debug_print(f"[ERROR] Both methods failed. Method 1: {e1}, Method 2: {e2}")
                        raise e1

        max_wait_time = 600
        start_time = time.time()

        while True:
            status = poller.status()
            if status == "succeeded":
                 break
            if status in ["failed", "canceled"]:
                # Attempt to get result even on failure for potential error details
                try:
                     result = poller.result()
                     # Optionally add failed result details to the exception message
                     error_details = f"Failed DI result details: {result}"
                except Exception as res_ex:
                     error_details = f"Could not get result details after failure: {res_ex}"
                raise Exception(f"Document analysis {status} for document. {error_details}")
            if time.time() - start_time > max_wait_time:
                raise TimeoutError(f"Document analysis took too long.")

            sleep_duration = 10 # Or adjust based on expected processing time
            time.sleep(sleep_duration)


        result = poller.result()

        pages_data = []

        if result.pages:
            for page in result.pages:
                page_number = page.page_number
                page_text = "" # Initialize page_text

                # --- METHOD 1: Preferred - Use spans and result.content ---
                if page.spans and result.content:
                    try:
                        page_content_parts = []
                        for span in page.spans:
                            start = span.offset
                            end = start + span.length
                            page_content_parts.append(result.content[start:end])
                        page_text = "".join(page_content_parts)
                    except Exception as span_ex:
                         # Silently ignore span extraction error and try next method
                         page_text = "" # Reset on error

                # --- METHOD 2: Fallback - Use lines if spans failed or weren't available ---
                if not page_text and page.lines:
                    try:
                        page_text = "\n".join(line.content for line in page.lines)
                    except Exception as line_ex:
                        # Silently ignore line extraction error and try next method
                        page_text = "" # Reset on error


                # --- METHOD 3: Last Resort Fallback - Use words (less accurate formatting) ---
                if not page_text and page.words:
                     try:
                        page_text = " ".join(word.content for word in page.words)
                     except Exception as word_ex:
                         # Silently ignore word extraction error
                         page_text = "" # Reset on error

                # If page_text is still empty after all attempts, it will be added as such

                pages_data.append({
                    "page_number": page_number,
                    "content": _append_selection_mark_summary(page_text.strip()) if normalized_extraction_mode == "layout" else page_text.strip()
                })
        # --- Fallback if NO pages were found at all, but top-level content exists ---
        elif result.content:
            fallback_content = result.content.strip()
            pages_data.append({
                "page_number": 1,
                "content": _append_selection_mark_summary(fallback_content) if normalized_extraction_mode == "layout" else fallback_content
            })
        # else: # No pages and no content, pages_data remains empty


        # Log the *processed* data using your existing logging function (optional)
        # add_file_task_to_file_processing_log(
        #     document_id=document_id,
        #     user_id=user_id,
        #     content=f"DI extraction processed data: {pages_data}"
        # )

        return pages_data

    except HttpResponseError as e:
        # Consider adding to your specific log here if needed, before re-raising
        # add_file_task_to_file_processing_log(document_id, user_id, f"HTTP error during DI: {e}")
        raise e
    except TimeoutError as e:
        # add_file_task_to_file_processing_log(document_id, user_id, f"Timeout error during DI: {e}")
        raise e
    except Exception as e:
        # add_file_task_to_file_processing_log(document_id, user_id, f"General error during DI: {e}")
        raise e


def resolve_extraction_engine_for_mode(extraction_mode, settings):
    """Resolve which engine backs the given extraction mode, plus a human-readable reason."""
    if extraction_mode != 'layout':
        return functions_settings.EXTRACTION_ENGINE_DOCUMENT_INTELLIGENCE, ''
    return functions_settings.resolve_enhanced_extraction_engine(settings)


# Persisted as the extraction engine reason and shown in workspace tooltips, so keep it short.
CONTENT_UNDERSTANDING_IMAGE_ANALYZER_REASON = (
    'Content Understanding found no text, so its image analyzer description was indexed'
)


def _describe_image_with_content_understanding(file_path, settings, analyze_image):
    """Return the Content Understanding image analyzer description, or '' when it has none."""
    try:
        description_text = str(analyze_image(file_path, settings=settings) or '').strip()
    except Exception as image_analyzer_error:
        log_event(
            f"[EXTRACTION_ENGINE] Content Understanding image analyzer failed for "
            f"{os.path.basename(file_path)}: {image_analyzer_error}. "
            "Falling back to Document Intelligence Layout.",
            level=logging.WARNING,
        )
        return ''

    if not description_text:
        log_event(
            f"[EXTRACTION_ENGINE] Content Understanding image analyzer returned no description for "
            f"{os.path.basename(file_path)}; falling back to Document Intelligence Layout.",
            level=logging.WARNING,
        )
    return description_text


def extract_content_with_extraction_engine(
    file_path,
    extraction_mode,
    extraction_engine=None,
    settings=None,
    pages=None,
    is_image=False,
):
    """Extract page content with the engine that backs the requested extraction mode.

    Standard extraction always uses Document Intelligence ``prebuilt-read``. Enhanced extraction
    prefers Azure AI Content Understanding, but always falls back to Document Intelligence
    ``prebuilt-layout`` so a Content Understanding outage never blocks ingestion.

    When ``is_image`` is set and the document analyzer finds no content, which is normal for a
    photo with no text, the Content Understanding image analyzer's description is returned as
    the image's single page instead. Only if that also yields nothing does extraction fall back
    to Document Intelligence Layout.

    Returns ``(pages_data, engine_used, fallback_reason)``.
    """
    resolved_settings = settings if settings is not None else get_settings()
    if extraction_engine is None:
        extraction_engine, _ = resolve_extraction_engine_for_mode(extraction_mode, resolved_settings)

    if (
        extraction_mode != 'layout'
        or extraction_engine != functions_settings.EXTRACTION_ENGINE_CONTENT_UNDERSTANDING
    ):
        return (
            extract_content_with_azure_di(file_path, extraction_mode=extraction_mode, pages=pages),
            functions_settings.EXTRACTION_ENGINE_DOCUMENT_INTELLIGENCE,
            '',
        )

    from functions_content_understanding import (
        analyze_image_with_content_understanding,
        extract_content_with_content_understanding,
    )

    try:
        content_understanding_pages = extract_content_with_content_understanding(
            file_path,
            pages=pages,
            settings=resolved_settings,
        )
        if content_understanding_pages:
            return (
                content_understanding_pages,
                functions_settings.EXTRACTION_ENGINE_CONTENT_UNDERSTANDING,
                '',
            )
        if is_image:
            image_description = _describe_image_with_content_understanding(
                file_path,
                resolved_settings,
                analyze_image_with_content_understanding,
            )
            if image_description:
                return (
                    [{'page_number': 1, 'content': image_description}],
                    functions_settings.EXTRACTION_ENGINE_CONTENT_UNDERSTANDING,
                    CONTENT_UNDERSTANDING_IMAGE_ANALYZER_REASON,
                )
        fallback_reason = (
            'Content Understanding returned no content, so Document Intelligence Layout was used'
        )
        log_event(
            f"[EXTRACTION_ENGINE] Content Understanding returned no content for "
            f"{os.path.basename(file_path)}; falling back to Document Intelligence Layout.",
            level=logging.WARNING,
        )
    except Exception as content_understanding_error:
        # The reason is persisted and rendered in workspace tooltips, so keep it short.
        error_summary = " ".join(str(content_understanding_error).split())[:240]
        fallback_reason = (
            f'Content Understanding failed ({error_summary}), '
            'so Document Intelligence Layout was used'
        )
        log_event(
            f"[EXTRACTION_ENGINE] Content Understanding failed for "
            f"{os.path.basename(file_path)}: {content_understanding_error}. "
            "Falling back to Document Intelligence Layout.",
            level=logging.WARNING,
        )

    return (
        extract_content_with_azure_di(file_path, extraction_mode='layout', pages=pages),
        functions_settings.EXTRACTION_ENGINE_DOCUMENT_INTELLIGENCE,
        fallback_reason,
    )


def extract_table_file(file_path, file_ext):
    try:
        if file_ext == '.csv':
            from functions_tabular_csv_query import read_tabular_csv
            df = read_tabular_csv(file_path)
        elif file_ext in ['.xls', '.xlsx', '.xlsm']:
            df = pandas.read_excel(file_path)
        else:
            raise ValueError("Unsupported file extension for table extraction.")
        
        # Return CSV format instead of HTML for more efficient storage and LLM processing
        # This drastically reduces token count and storage costs
        csv_content = df.to_csv(index=False)
        return csv_content
    except Exception as e:
        raise

def extract_pdf_metadata(pdf_path):
    """
    Returns a tuple (title, author, subject, keywords) from the given PDF, using PyMuPDF.
    """
    try:
        with fitz.open(pdf_path) as doc:
            meta = doc.metadata
            pdf_title = meta.get("title", "")
            pdf_author = meta.get("author", "")
            pdf_subject = meta.get("subject", "")
            pdf_keywords = meta.get("keywords", "")

            return pdf_title, pdf_author, pdf_subject, pdf_keywords

    except Exception as e:
        print(f"Error extracting PDF metadata: {e}")
        return "", "", "", ""
    
def extract_docx_metadata(docx_path):
    """
    Returns a tuple (title, author) from the given DOCX, using python-docx.
    """
    try:
        doc = docx.Document(docx_path)
        core_props = doc.core_properties
        doc_title = core_props.title or ''
        doc_author = core_props.author or ''
        return doc_title, doc_author
    except Exception as e:
        print(f"Error extracting DOCX metadata: {e}")
        return '', ''


def _normalize_legacy_doc_metadata_value(value):
    """Convert OLE metadata values into trimmed strings."""
    if value is None:
        return ''

    if isinstance(value, bytes):
        for encoding in ('utf-8', 'utf-16le', 'cp1252', 'latin1'):
            try:
                value = value.decode(encoding)
                break
            except Exception:
                continue
        else:
            value = value.decode('utf-8', errors='ignore')

    return str(value).strip().strip('\x00').strip()


def _parse_metadata_keywords(value):
    """Parse metadata keywords into a normalized list of values."""
    normalized_value = _normalize_legacy_doc_metadata_value(value)
    if not normalized_value:
        return []

    return [keyword.strip() for keyword in re.split(r'[;,]', normalized_value) if keyword.strip()]


def extract_legacy_doc_metadata(doc_path):
    """Return title and author from a legacy OLE Word document when available."""
    try:
        if not olefile.isOleFile(doc_path):
            return '', ''

        ole = olefile.OleFileIO(doc_path)
        try:
            metadata = ole.get_metadata()
            doc_title = _normalize_legacy_doc_metadata_value(getattr(metadata, 'title', ''))
            doc_author = _normalize_legacy_doc_metadata_value(getattr(metadata, 'author', ''))

            if not doc_author:
                doc_author = _normalize_legacy_doc_metadata_value(getattr(metadata, 'last_saved_by', ''))

            return doc_title, doc_author
        finally:
            ole.close()
    except Exception as e:
        print(f"Error extracting DOC metadata: {e}")
        return '', ''


def extract_pptx_metadata(pptx_path):
    """Return title, author, subject, and keywords from an OOXML PowerPoint file."""
    namespaces = {
        'cp': 'http://schemas.openxmlformats.org/package/2006/metadata/core-properties',
        'dc': 'http://purl.org/dc/elements/1.1/',
    }

    try:
        with zipfile.ZipFile(pptx_path) as archive:
            try:
                core_properties = archive.read('docProps/core.xml')
            except KeyError:
                return '', '', '', []

        root = ElementTree.fromstring(core_properties)
        ppt_title = (root.findtext('dc:title', default='', namespaces=namespaces) or '').strip()
        ppt_author = (root.findtext('dc:creator', default='', namespaces=namespaces) or '').strip()
        ppt_subject = (root.findtext('dc:subject', default='', namespaces=namespaces) or '').strip()
        ppt_keywords = _parse_metadata_keywords(
            root.findtext('cp:keywords', default='', namespaces=namespaces) or ''
        )
        return ppt_title, ppt_author, ppt_subject, ppt_keywords
    except Exception as e:
        print(f"Error extracting PPTX metadata: {e}")
        return '', '', '', []


def _clean_legacy_ppt_text_fragment(text):
    """Normalize legacy PowerPoint text atoms into readable slide text."""
    if not text:
        return ''

    normalized_text = (
        text
        .replace('\r', '\n')
        .replace('\x0b', '\n')
        .replace('\x0c', '\n')
        .replace('\x00', '')
    )
    normalized_text = re.sub(r'[\x01-\x08\x0e-\x1f]', ' ', normalized_text)
    normalized_text = re.sub(r'[ \t]{2,}', ' ', normalized_text)
    normalized_text = re.sub(r'\n{3,}', '\n\n', normalized_text)
    return normalized_text.strip()


def extract_legacy_ppt_pages(file_path):
    """Extract slide text from a legacy OLE PowerPoint .ppt file."""
    if not olefile.isOleFile(file_path):
        raise Exception("File is not a valid OLE compound document")

    ole = olefile.OleFileIO(file_path)
    try:
        if not ole.exists('PowerPoint Document'):
            raise Exception("Missing PowerPoint Document stream")

        document_stream = ole.openstream('PowerPoint Document').read()
    finally:
        ole.close()

    slide_fragments = {}
    slide_counter = 0

    def walk_records(start_offset, end_offset, current_slide_number=None):
        nonlocal slide_counter

        offset = start_offset
        while offset + 8 <= end_offset:
            record_header = struct.unpack_from('<H', document_stream, offset)[0]
            record_version = record_header & 0x000F
            record_type = struct.unpack_from('<H', document_stream, offset + 2)[0]
            record_length = struct.unpack_from('<I', document_stream, offset + 4)[0]
            payload_start = offset + 8
            payload_end = payload_start + record_length

            if payload_end > end_offset:
                return

            next_slide_number = current_slide_number
            if record_type == 1006:
                slide_counter += 1
                next_slide_number = slide_counter
                slide_fragments.setdefault(next_slide_number, [])

            if record_type in {4000, 4008} and next_slide_number is not None:
                if record_type == 4000:
                    raw_text = document_stream[payload_start:payload_end].decode('utf-16le', errors='ignore')
                else:
                    raw_text = document_stream[payload_start:payload_end].decode('cp1252', errors='ignore')

                cleaned_text = _clean_legacy_ppt_text_fragment(raw_text)
                if cleaned_text:
                    fragments = slide_fragments.setdefault(next_slide_number, [])
                    if not fragments or fragments[-1] != cleaned_text:
                        fragments.append(cleaned_text)

            if record_version == 0x0F:
                walk_records(payload_start, payload_end, next_slide_number)

            offset = payload_end

    walk_records(0, len(document_stream))

    pages = []
    non_empty_slide_count = 0
    for slide_number in range(1, slide_counter + 1):
        slide_text = "\n".join(slide_fragments.get(slide_number, []))
        slide_text = re.sub(r'\n{3,}', '\n\n', slide_text).strip()
        if slide_text:
            non_empty_slide_count += 1

        pages.append({
            'page_number': slide_number,
            'content': slide_text,
        })

    if non_empty_slide_count == 0:
        raise Exception("Could not locate readable slide text in the presentation")

    return pages


def extract_legacy_ppt_metadata(ppt_path):
    """Return title, author, subject, and keywords from a legacy OLE PowerPoint file."""
    try:
        if not olefile.isOleFile(ppt_path):
            return '', '', '', []

        ole = olefile.OleFileIO(ppt_path)
        try:
            metadata = ole.get_metadata()
            ppt_title = _normalize_legacy_doc_metadata_value(getattr(metadata, 'title', ''))
            ppt_author = _normalize_legacy_doc_metadata_value(getattr(metadata, 'author', ''))
            ppt_subject = _normalize_legacy_doc_metadata_value(getattr(metadata, 'subject', ''))
            ppt_keywords = _parse_metadata_keywords(getattr(metadata, 'keywords', ''))

            if not ppt_author:
                ppt_author = _normalize_legacy_doc_metadata_value(getattr(metadata, 'last_saved_by', ''))

            return ppt_title, ppt_author, ppt_subject, ppt_keywords
        finally:
            ole.close()
    except Exception as e:
        print(f"Error extracting PPT metadata: {e}")
        return '', '', '', []


def extract_presentation_metadata(file_path, file_extension=None):
    """Extract metadata from supported PowerPoint presentation formats."""
    resolved_extension = (file_extension or os.path.splitext(file_path)[1]).lower()

    if resolved_extension == '.ppt':
        return extract_legacy_ppt_metadata(file_path)

    if resolved_extension == '.pptx':
        return extract_pptx_metadata(file_path)

    return '', '', '', []


def extract_word_text(file_path, file_extension=None):
    """Extract text from supported Word document formats."""
    resolved_extension = (file_extension or os.path.splitext(file_path)[1]).lower()

    if resolved_extension == '.doc':
        if olefile.isOleFile(file_path):
            text = extract_legacy_doc_text(file_path)
        else:
            text = extract_docx_text(file_path)
    elif resolved_extension in {'.docx', '.docm'}:
        text = extract_docx_text(file_path)
    else:
        raise ValueError(f"Unsupported Word document extension: {resolved_extension}")
    capture_text_before_chunking(text)
    return text


def extract_word_metadata(file_path, file_extension=None):
    """Extract title and author metadata from supported Word document formats."""
    resolved_extension = (file_extension or os.path.splitext(file_path)[1]).lower()

    if resolved_extension == '.doc':
        if olefile.isOleFile(file_path):
            return extract_legacy_doc_metadata(file_path)
        return extract_docx_metadata(file_path)

    if resolved_extension in {'.docx', '.docm'}:
        return extract_docx_metadata(file_path)

    return '', ''

def parse_authors(author_input):
    """
    Converts any input (None, string, list, comma-delimited, etc.)
    into a list of author strings.
    """
    if not author_input:
        # Covers None or empty string
        return []

    # If it's already a list, just return it (with stripping)
    if isinstance(author_input, list):
        return [a.strip() for a in author_input if a.strip()]

    # Otherwise, assume it's a string and parse by common delimiters (comma, semicolon)
    if isinstance(author_input, str):
        # e.g. "John Doe, Jane Smith; Bob Brown"
        authors = re.split(r'[;,]', author_input)
        authors = [a.strip() for a in authors if a.strip()]
        return authors

    # If it's some other unexpected data type, fallback to empty
    return []

def chunk_text(text, chunk_size=2000, overlap=200):
    capture_text_before_chunking(text)
    try:
        words = text.split()
        chunks = []
        for i in range(0, len(words), chunk_size - overlap):
            chunk = ' '.join(words[i:i + chunk_size])
            chunks.append(chunk)
        return chunks
    except Exception as e:
        # Log the exception or handle it as needed
        print(f"Error in chunk_text: {e}")
        raise e  # Re-raise the exception to propagate it


# Separators ordered from strongest structural boundary to weakest, so a split lands on a blank
# line before a line break before a space. Word-limited splitting deliberately omits the empty
# separator so a split never lands mid-word; character-limited splitting includes it because it is
# a hard safety bound and must be able to break an unbroken run of text.
CHUNK_SPLIT_SEPARATORS_WORDS = ["\n\n", "\n", " "]
CHUNK_SPLIT_SEPARATORS_CHARACTERS = ["\n\n", "\n", " ", ""]


def count_words(text):
    """Count words the same way chunk budgeting does elsewhere in the pipeline."""
    if not text:
        return 0
    return len(text.split())


def split_text_by_word_limit(text, max_words, overlap_ratio=0.1):
    """Split text so no piece exceeds max_words, breaking on the strongest boundary available.

    Returns the text unchanged when it already fits, so callers can apply this unconditionally.
    Content is never truncated; a small overlap keeps context across a split.
    """
    if not text or not str(text).strip():
        return []

    try:
        max_words = int(max_words)
    except Exception:
        return [text]

    if max_words <= 0 or count_words(text) <= max_words:
        return [text]

    overlap = max(0, min(int(max_words * overlap_ratio), max_words - 1))

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=max_words,
        chunk_overlap=overlap,
        length_function=count_words,
        separators=CHUNK_SPLIT_SEPARATORS_WORDS,
        is_separator_regex=False,
    )

    pieces = [piece for piece in splitter.split_text(text) if piece and piece.strip()]
    return pieces or [text]


def split_oversized_chunks(chunks, max_characters):
    """Bound every chunk to max_characters, preserving order and never truncating content.

    This is the authoritative backstop for the embedding token limit. It runs after any word-based
    sizing because word counts cannot predict how badly markdown tables, code fences, or long URLs
    tokenize, and because merging small chunks can inflate one past its intended target.
    """
    if not chunks:
        return []

    try:
        max_characters = int(max_characters)
    except Exception:
        return list(chunks)

    if max_characters <= 0:
        return list(chunks)

    splitter = None
    bounded_chunks = []

    for chunk in chunks:
        if chunk is None:
            continue

        if len(chunk) <= max_characters:
            bounded_chunks.append(chunk)
            continue

        if splitter is None:
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=max_characters,
                chunk_overlap=0,
                length_function=len,
                separators=CHUNK_SPLIT_SEPARATORS_CHARACTERS,
                is_separator_regex=False,
            )

        pieces = [piece for piece in splitter.split_text(chunk) if piece and piece.strip()]
        bounded_chunks.extend(pieces or [chunk])

    return bounded_chunks


def chunk_word_file_into_pages(di_pages, chunk_size=WORD_CHUNK_SIZE):
    """
    Chunk Azure DI Word pages into smaller word-based segments.

    Args:
        di_pages (list): Pages returned from DI with page_number/content keys.
        chunk_size (int): Target number of words per chunk (defaults to config).

    Returns:
        list: A list of dicts with chunked content and sequence numbers.
    """
    new_pages = []
    current_chunk_content = []
    current_word_count = 0
    new_page_number = 1 # This will represent the chunk number

    for page in di_pages:
        page_content = page.get("content", "")
        # Split content into words (handling various whitespace)
        words = re.findall(r'\S+', page_content)

        for word in words:
            current_chunk_content.append(word)
            current_word_count += 1

            # If the chunk reaches the desired size, finalize it
            if current_word_count >= chunk_size:
                chunk_text = " ".join(current_chunk_content)
                new_pages.append({
                    "page_number": new_page_number,
                    "content": chunk_text
                })
                # Reset for the next chunk
                current_chunk_content = []
                current_word_count = 0
                new_page_number += 1

    # Add any remaining words as the last chunk, if any exist
    if current_chunk_content:
        chunk_text = " ".join(current_chunk_content)
        new_pages.append({
            "page_number": new_page_number,
            "content": chunk_text
        })

    # If the input was empty or contained no words, return an empty list
    # or a single empty chunk depending on desired behavior.
    # Current logic returns empty list if no words.
    return new_pages


def _parse_retry_after_seconds(response_headers):
    """Return retry delay in seconds from rate-limit headers when available."""
    if response_headers is None:
        return None

    for header_name in ('retry-after-ms', 'x-ms-retry-after-ms'):
        try:
            retry_ms = response_headers.get(header_name)
            if retry_ms is None:
                continue

            retry_after = float(retry_ms) / 1000
            if retry_after > 0:
                return retry_after
        except (TypeError, ValueError):
            continue

    retry_header = response_headers.get('retry-after')
    try:
        retry_after = float(retry_header)
        if retry_after > 0:
            return retry_after
    except (TypeError, ValueError):
        pass

    if not retry_header:
        return None

    retry_date_tuple = email.utils.parsedate_tz(retry_header)
    if retry_date_tuple is None:
        return None

    retry_after = float(email.utils.mktime_tz(retry_date_tuple) - time.time())
    if retry_after <= 0:
        return None

    return retry_after


def _get_rate_limit_wait_time(rate_limit_error, fallback_delay):
    """Prefer service-provided retry timing and fall back to jittered backoff."""
    response = getattr(rate_limit_error, 'response', None)
    response_headers = getattr(response, 'headers', None)
    retry_after = _parse_retry_after_seconds(response_headers)

    if retry_after is not None and retry_after <= 60:
        return retry_after

    return fallback_delay * random.uniform(1.0, 1.5)

def generate_embedding(
    text,
    max_retries=5,
    initial_delay=1.0,
    delay_multiplier=2.0,
    *,
    purpose="document",
    profile=None,
):
    """Return one vector and optional usage using the global embedding binding."""
    return generate_embeddings_batch(
        [text], purpose=purpose, profile=profile,
        max_retries=max_retries, initial_delay=initial_delay,
        delay_multiplier=delay_multiplier,
    )[0]

def generate_embeddings_batch(
    texts,
    batch_size=16,
    max_retries=5,
    initial_delay=1.0,
    delay_multiplier=2.0,
    *,
    purpose="document",
    profile=None,
):
    """Return ordered vectors and optional usage, bounded by the model's batch limits."""
    if isinstance(texts, (list, tuple)) and not texts:
        return []
    settings = read_embedding_settings()
    current_profile = active_embedding_profile(settings)
    if profile is not None and profile.profile_id != current_profile.profile_id:
        raise AIConnectionError("The embedding model changed. Retry the operation.", "embedding_profile_changed")
    with embedding_query_slot(current_profile.profile_id):
        pass
    return generate_embedding_batch(
        texts, settings=settings, purpose=purpose, profile=profile or current_profile,
        batch_size=batch_size, max_retries=max_retries, initial_delay=initial_delay,
        delay_multiplier=delay_multiplier, retry_delay=_get_rate_limit_wait_time,
    )
