# analyze_deliverable_contract_fixture.py
"""Deterministic 200-row oracle for Analyze deliverable contract tests."""

from copy import deepcopy
from datetime import date, timedelta


ASSESSMENT_DATE = date(2026, 8, 12)

FINANCIAL_REVIEW_SOURCE_COLUMNS = [
    "Item_ID",
    "Review_Date",
    "Due_Date",
    "Invoice_Amount",
    "Spend_Category",
    "Vendor_Risk",
    "Control_Status",
    "Exception_Count",
    "Owner_Response",
    "Escalation_Flag",
]

FINANCIAL_REVIEW_OUTPUT_COLUMNS = [
    "Item_ID",
    "Timeline_Status",
    "Spend_Risk",
    "Control_Concern",
    "Owner_Response_Status",
    "Escalation_Required",
    "Overall_Attention",
    "Review_Window",
    "Recommended_Action",
]

FINANCIAL_REVIEW_PROMPT = """
Use assessment date 2026-08-12. Create one output row per source row in source order.
Return exactly these columns: Item_ID, Timeline_Status, Spend_Risk, Control_Concern,
Owner_Response_Status, Escalation_Required, Overall_Attention, Review_Window,
Recommended_Action.

Rules:
1. Timeline_Status is Overdue when Due_Date is before 2026-08-12, Due Soon when Due_Date
   is on or before 2026-09-11, otherwise On Track.
2. Spend_Risk is High Spend Risk for Invoice_Amount >= 75000 or Vendor_Risk High,
   Moderate Spend Risk for Invoice_Amount >= 25000 or Vendor_Risk Medium, otherwise Low Spend Risk.
3. Control_Concern is Control Concern when Control_Status is Missing Approval or Policy Exception,
   or Exception_Count is at least 2; otherwise No Control Concern.
4. Owner_Response_Status is Responded when Owner_Response is Received; otherwise Needs Response.
5. Escalation_Required is Yes when Escalation_Flag is Y or an overdue item needs response.
6. Overall_Attention uses ordered conditions: High Attention when escalation is required, or a
   control concern needs response, or spend risk is high; Monitor when timeline is not On Track,
   spend risk is moderate, or a control concern exists; otherwise Low Attention.
7. Review_Window is Past Due, Due Today, Within 30 Days, or Beyond 30 Days using Due_Date.
8. Recommended_Action follows Overall_Attention first, then overdue and due-soon timelines.
""".strip()

KNOWN_FAULTY_SEARCH_VALUE_MISMATCHES = [
    ("FRI-062", "Overall_Attention", "Monitor"),
    ("FRI-073", "Overall_Attention", "Monitor"),
    ("FRI-115", "Timeline_Status", "Due Soon"),
    ("FRI-141", "Timeline_Status", "Due Soon"),
    ("FRI-159", "Timeline_Status", "Due Soon"),
]


def _iso_date(days_from_assessment):
    return (ASSESSMENT_DATE + timedelta(days=days_from_assessment)).isoformat()


def build_financial_review_source_rows():
    """Build 200 sanitized source rows with boundary and dependency cases."""
    categories = ["Software", "Travel", "Facilities", "Services", "Hardware"]
    vendor_risks = ["Low", "Medium", "Low", "High"]
    control_statuses = ["Complete", "Missing Approval", "Complete", "Policy Exception"]
    source_rows = []

    for item_number in range(1, 201):
        due_delta = ((item_number * 7) % 96) - 20
        row = {
            "Item_ID": f"FRI-{item_number:03d}",
            "Review_Date": _iso_date(-(item_number % 21)),
            "Due_Date": _iso_date(due_delta),
            "Invoice_Amount": 8000 + ((item_number * 3100) % 98000),
            "Spend_Category": categories[item_number % len(categories)],
            "Vendor_Risk": vendor_risks[item_number % len(vendor_risks)],
            "Control_Status": control_statuses[item_number % len(control_statuses)],
            "Exception_Count": item_number % 3,
            "Owner_Response": "Missing" if item_number % 5 in {0, 2} else "Received",
            "Escalation_Flag": "Y" if item_number % 37 == 0 else "N",
        }
        source_rows.append(row)

    boundary_overrides = {
        1: {"Due_Date": _iso_date(-1)},
        2: {"Due_Date": _iso_date(0)},
        3: {"Due_Date": _iso_date(30)},
        4: {"Due_Date": _iso_date(31)},
        62: {
            "Due_Date": _iso_date(45),
            "Invoice_Amount": 19000,
            "Vendor_Risk": "Low",
            "Control_Status": "Missing Approval",
            "Exception_Count": 2,
            "Owner_Response": "Missing",
            "Escalation_Flag": "N",
        },
        73: {
            "Due_Date": _iso_date(52),
            "Invoice_Amount": 22000,
            "Vendor_Risk": "Low",
            "Control_Status": "Policy Exception",
            "Exception_Count": 1,
            "Owner_Response": "Missing",
            "Escalation_Flag": "N",
        },
        115: {
            "Due_Date": _iso_date(31),
            "Invoice_Amount": 12000,
            "Vendor_Risk": "Low",
            "Control_Status": "Complete",
            "Exception_Count": 0,
            "Owner_Response": "Received",
            "Escalation_Flag": "N",
        },
        141: {
            "Due_Date": _iso_date(45),
            "Invoice_Amount": 18000,
            "Vendor_Risk": "Low",
            "Control_Status": "Complete",
            "Exception_Count": 0,
            "Owner_Response": "Received",
            "Escalation_Flag": "N",
        },
        159: {
            "Due_Date": _iso_date(60),
            "Invoice_Amount": 21000,
            "Vendor_Risk": "Low",
            "Control_Status": "Complete",
            "Exception_Count": 0,
            "Owner_Response": "Received",
            "Escalation_Flag": "N",
        },
    }
    for item_number, updates in boundary_overrides.items():
        source_rows[item_number - 1].update(updates)

    return [
        {column_name: row[column_name] for column_name in FINANCIAL_REVIEW_SOURCE_COLUMNS}
        for row in source_rows
    ]


def _timeline_status(due_date):
    parsed_due_date = date.fromisoformat(due_date)
    if parsed_due_date < ASSESSMENT_DATE:
        return "Overdue"
    if parsed_due_date <= ASSESSMENT_DATE + timedelta(days=30):
        return "Due Soon"
    return "On Track"


def _review_window(due_date):
    parsed_due_date = date.fromisoformat(due_date)
    if parsed_due_date < ASSESSMENT_DATE:
        return "Past Due"
    if parsed_due_date == ASSESSMENT_DATE:
        return "Due Today"
    if parsed_due_date <= ASSESSMENT_DATE + timedelta(days=30):
        return "Within 30 Days"
    return "Beyond 30 Days"


def _spend_risk(row):
    amount = int(row["Invoice_Amount"])
    vendor_risk = str(row["Vendor_Risk"])
    if amount >= 75000 or vendor_risk == "High":
        return "High Spend Risk"
    if amount >= 25000 or vendor_risk == "Medium":
        return "Moderate Spend Risk"
    return "Low Spend Risk"


def _control_concern(row):
    if row["Control_Status"] in {"Missing Approval", "Policy Exception"}:
        return "Control Concern"
    if int(row["Exception_Count"]) >= 2:
        return "Control Concern"
    return "No Control Concern"


def _owner_response_status(row):
    return "Responded" if row["Owner_Response"] == "Received" else "Needs Response"


def build_expected_financial_review_output_rows(source_rows=None):
    """Compute the expected nine-column output with an independent deterministic oracle."""
    expected_rows = []
    for row in list(source_rows or build_financial_review_source_rows()):
        timeline_status = _timeline_status(row["Due_Date"])
        spend_risk = _spend_risk(row)
        control_concern = _control_concern(row)
        owner_response_status = _owner_response_status(row)
        escalation_required = (
            "Yes"
            if row["Escalation_Flag"] == "Y"
            or (timeline_status == "Overdue" and owner_response_status == "Needs Response")
            else "No"
        )
        if (
            escalation_required == "Yes"
            or (control_concern == "Control Concern" and owner_response_status == "Needs Response")
            or spend_risk == "High Spend Risk"
        ):
            overall_attention = "High Attention"
        elif (
            timeline_status != "On Track"
            or spend_risk == "Moderate Spend Risk"
            or control_concern == "Control Concern"
        ):
            overall_attention = "Monitor"
        else:
            overall_attention = "Low Attention"

        if overall_attention == "High Attention":
            recommended_action = "Escalate review"
        elif timeline_status == "Overdue":
            recommended_action = "Review overdue item"
        elif timeline_status == "Due Soon":
            recommended_action = "Schedule follow-up"
        else:
            recommended_action = "Routine monitoring"

        expected_rows.append({
            "Item_ID": row["Item_ID"],
            "Timeline_Status": timeline_status,
            "Spend_Risk": spend_risk,
            "Control_Concern": control_concern,
            "Owner_Response_Status": owner_response_status,
            "Escalation_Required": escalation_required,
            "Overall_Attention": overall_attention,
            "Review_Window": _review_window(row["Due_Date"]),
            "Recommended_Action": recommended_action,
        })
    return expected_rows


def build_source_shaped_analyze_output_rows(source_rows=None):
    """Return the observed Analyze failure shape: unchanged source rows."""
    return deepcopy(list(source_rows or build_financial_review_source_rows()))


def build_faulty_search_output_rows(expected_rows=None, include_lineage=True):
    """Return the observed Search failure shape with two lineage fields and five wrong values."""
    rows = deepcopy(list(expected_rows or build_expected_financial_review_output_rows()))
    by_id = {row["Item_ID"]: row for row in rows}
    for item_id, field_name, faulty_value in KNOWN_FAULTY_SEARCH_VALUE_MISMATCHES:
        by_id[item_id][field_name] = faulty_value
    if include_lineage:
        for row_number, row in enumerate(rows, start=1):
            row["source_row_number"] = row_number
            row["source_row_identity"] = row["Item_ID"]
    return rows


def find_value_mismatches(expected_rows, actual_rows, field_names=None, identity_field="Item_ID"):
    """Return deterministic value mismatches for test assertions."""
    fields = list(field_names or FINANCIAL_REVIEW_OUTPUT_COLUMNS)
    mismatches = []
    for expected_row, actual_row in zip(list(expected_rows or []), list(actual_rows or [])):
        identity = expected_row.get(identity_field)
        for field_name in fields:
            if expected_row.get(field_name) != actual_row.get(field_name):
                mismatches.append({
                    "identity": identity,
                    "field": field_name,
                    "expected": expected_row.get(field_name),
                    "actual": actual_row.get(field_name),
                })
    return mismatches
