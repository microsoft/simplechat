# test_orchestration_tabular_preparation.py
"""
Functional test for complete tabular preparation and evidence-first calculation.
Version: 0.261.446
Implemented in: 0.261.446

This test keeps a portable 104-row synthetic fixture local while proving full
rules, late columns/rows, signed allocation, cumulative dates and unknown chains.
"""

import csv
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
import io

import pytest

from functions_tabular_merge import TabularMergeError
from functions_tabular_merge import (
    TabularMergeLimits, TabularMergeSource, prepare_tabular_source_context,
)
from functions_tabular_relational import calculate_relational_sources


def _rule(label):
    return (
        f"FILE RULE FOR ALL ROWS: {label}. Read every original row and the complete ordered "
        "header. Signed credits remain separate evidence. Missing links are unknown, never zero. "
        "Round only declared USD allocations, preserve revision intervals and exact identifiers. "
        + ("This fixture deliberately places substantive text after the early preview. " * 6)
    )


def _source_bytes(columns, rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode()


def _common(rule):
    return {
        "exercise": "SYNTHETIC", "reporting_period": "2026-09",
        "cutoff_utc": "2026-09-30T23:59:59Z",
        "evidence_as_of_utc": "2026-10-05T23:59:59Z",
        "source_rule": rule,
    }


def synthetic_sources():
    ledger_columns = [
        "exercise", "reporting_period", "cutoff_utc", "evidence_as_of_utc", "source_rule",
        "posting_id", "transaction_id", "program", "posting_date", "status", "currency",
        "native_amount", "posted_usd", "invoice_ref", "vendor_ref", "vendor_name", "description",
    ]
    bank_columns = [
        "exercise", "reporting_period", "cutoff_utc", "evidence_as_of_utc", "source_rule",
        "allocation_id", "settlement_id", "ledger_posting_id", "settlement_date", "status",
        "currency", "settled_usd", "payment_instruction_ref", "reversal_of_allocation_id",
        "bank_reference",
    ]
    invoice_columns = [
        "exercise", "reporting_period", "cutoff_utc", "evidence_as_of_utc", "source_rule",
        "invoice_line_id", "invoice_ref", "line_number", "invoice_date", "document_status",
        "document_type", "invoice_family_id", "replaces_invoice_ref", "credit_against_invoice_ref",
        "po_line_id", "vendor_ref", "currency", "quantity", "unit_price_native",
        "line_amount_native",
    ]
    po_columns = [
        "exercise", "reporting_period", "cutoff_utc", "evidence_as_of_utc", "source_rule",
        "po_line_id", "po_ref", "line_number", "program", "budget_line_id", "approval_date",
        "order_status", "currency", "ordered_qty", "unit_price_native", "committed_usd",
        "obligated_usd", "obligation_id", "contract_line_id",
    ]
    contract_columns = [
        "exercise", "reporting_period", "cutoff_utc", "evidence_as_of_utc", "source_rule",
        "contract_line_id", "revision_id", "effective_from", "effective_to",
        "currency", "ceiling_usd", "contract_reference",
    ]

    ledger_rule = _rule("September POSTED ledger rows and signed credits")
    bank_rule = _rule("SETTLED bank allocations through the evidence horizon")
    invoice_rule = _rule("Invoice-line proportional signed USD allocation")
    po_rule = _rule("Approved cutoff purchase-order line authority")
    contract_rule = _rule("Inclusive effective contract revisions and cumulative settled USD")

    ledger_values = [
        ("L01", "I01", "2026-09-02", "1000.00"),
        ("L02", "I02", "2026-09-04", "2400.00"),
        ("L03", "CN02", "2026-09-05", "-400.00"),
        ("L04", "I04", "2026-09-09", "3000.00"),
        ("L05", "I05", "2026-09-12", "1500.00"),
        ("L06", "I06", "2026-09-15", "800.00"),
        ("L07", "I07", "2026-09-20", "2000.00"),
        ("L08", "I08", "2026-09-24", "600.00"),
        ("L09", "I09", "2026-09-27", "900.00"),
        ("L10", "I10", "2026-09-30", "700.00"),
        ("L11", "I11", "2026-09-30", "9999.00"),
        ("L12", "I12", "2026-08-31", "500.00"),
        ("L13", "I13", "2026-10-01", "600.00"),
        ("L14", "CN08", "2026-09-28", "-100.00"),
        ("L15", "I15", "2026-09-06", "1200.00"),
        ("L16", "CN15", "2026-09-07", "-1200.00"),
        ("L17", "I15R", "2026-09-08", "1150.00"),
        ("L18", "I18", "2026-09-18", "400.00"),
        ("L19", "I19-MISSING", "2026-09-22", "750.00"),
        ("L20", "I20", "2026-09-10", "1100.00"),
        ("L21", "I21", "2026-09-17", "1100.00"),
        ("L22", "I22", "2026-09-21", "80.00"),
        ("L23", "I23", "2026-09-25", "12.02"),
        ("L24", "I24", "2026-09-29", "300.00"),
    ]
    ledger = []
    for posting_id, invoice_ref, posting_date, amount in ledger_values:
        ledger.append({
            **_common(ledger_rule), "posting_id": posting_id, "transaction_id": f"T-{posting_id}",
            "program": "OPS", "posting_date": posting_date,
            "status": "DRAFT" if posting_id == "L11" else "POSTED", "currency": "USD",
            "native_amount": amount, "posted_usd": amount, "invoice_ref": invoice_ref,
            "vendor_ref": f"V-{posting_id}", "vendor_name": "Synthetic supplier",
            "description": f"Late source column row {posting_id}",
        })

    bank_values = [
        ("BA001", "L01", "2026-09-03", "600.00"), ("BA002", "L01", "2026-09-04", "400.00"),
        ("BA003", "L02", "2026-09-05", "2400.00"), ("BA004", "L03", "2026-09-06", "-400.00"),
        ("BA005", "L04", "2026-09-12", "3000.00"), ("BA006", "L05", "2026-09-15", "1500.00"),
        ("BA007", "L06", "2026-09-20", "800.00"), ("BA008", "L07", "2026-09-23", "2000.00"),
        ("BA009", "L08", "2026-09-25", "500.00"), ("BA010", "L14", "2026-09-29", "-100.00"),
        ("BA011", "L09", "2026-10-02", "900.00"), ("BA012", "L10", "2026-09-30", "900.00"),
        ("BA013", "", "2026-09-29", "250.00"), ("BA014", "L12", "2026-09-02", "500.00"),
        ("BA015", "L11", "2026-09-28", "9999.00"), ("BA016", "L15", "2026-09-07", "1200.00"),
        ("BA017", "L16", "2026-09-08", "-1200.00"), ("BA018", "L17", "2026-09-09", "1150.00"),
        ("BA019", "L18", "2026-09-19", "400.00"), ("BA020", "L18", "2026-09-20", "400.00"),
        ("BA021", "L19", "2026-09-23", "750.00"), ("BA022", "L20", "2026-09-11", "1100.00"),
        ("BA023", "L21", "2026-09-18", "1100.00"), ("BA024", "L22", "2026-09-22", "80.00"),
        ("BA025", "L23", "2026-09-26", "12.02"), ("BA026", "L24", "2026-09-30", "300.00"),
    ]
    bank = []
    for allocation_id, posting_id, day, amount in bank_values:
        bank.append({
            **_common(bank_rule), "allocation_id": allocation_id,
            "settlement_id": f"B-{allocation_id}", "ledger_posting_id": posting_id,
            "settlement_date": day, "status": "VOID" if allocation_id == "BA015" else "SETTLED",
            "currency": "USD", "settled_usd": amount,
            "payment_instruction_ref": f"PMT-{allocation_id}",
            "reversal_of_allocation_id": "", "bank_reference": f"BR-{allocation_id}",
        })

    invoice_values = [
        ("IL01", "I01", "PO01", "1000.00"),
        ("IL02A", "I02", "PO02A", "1000.00"), ("IL02B", "I02", "PO02B", "1400.00"),
        ("IL03", "CN02", "PO02B", "-400.00"), ("IL04", "I04", "PO04", "3000.00"),
        ("IL05", "I05", "PO05", "1500.00"), ("IL06", "I06", "PO06", "800.00"),
        ("IL07", "I07", "PO07", "2000.00"), ("IL08", "I08", "PO08", "600.00"),
        ("IL09", "I09", "PO09", "900.00"), ("IL10", "I10", "PO10", "700.00"),
        ("IL11", "I11", "PO11", "9999.00"), ("IL12", "I12", "PO12", "500.00"),
        ("IL13", "I13", "PO13", "600.00"), ("IL14", "CN08", "PO08", "-100.00"),
        ("IL15", "I15", "PO15", "1200.00"), ("IL16", "CN15", "PO15", "-1200.00"),
        ("IL17", "I15R", "PO15", "1150.00"), ("IL18", "I18", "PO18", "400.00"),
        ("IL20", "I20", "PO20", "1100.00"), ("IL21", "I21", "PO21", "1100.00"),
        ("IL22", "I22", "PO22", "100.00"), ("IL23", "I23", "PO23", "10.01"),
        ("IL24", "I24", "PO24", "300.00"),
    ]
    invoice = []
    for index, (line_id, invoice_ref, po_line_id, amount) in enumerate(invoice_values, 1):
        invoice.append({
            **_common(invoice_rule), "invoice_line_id": line_id, "invoice_ref": invoice_ref,
            "line_number": "1", "invoice_date": f"2026-09-{min(index, 28):02d}",
            "document_status": "ISSUED", "document_type": "CREDIT_NOTE" if amount.startswith("-") else "INVOICE",
            "invoice_family_id": f"F-{invoice_ref}", "replaces_invoice_ref": "",
            "credit_against_invoice_ref": "", "po_line_id": po_line_id,
            "vendor_ref": f"V-{invoice_ref}", "currency": "USD", "quantity": "1",
            "unit_price_native": amount, "line_amount_native": amount,
        })

    po_values = [
        ("PO01", "CA", "1000.00"), ("PO02A", "CA", "1000.00"), ("PO02B", "CA", "1400.00"),
        ("PO04", "CB", "2500.00"), ("PO05", "CC", "2000.00"), ("PO06", "CD", "800.00"),
        ("PO07", "CB", "1500.00"), ("PO08", "CC", "600.00"), ("PO09", "CD", "900.00"),
        ("PO10", "CB", "700.00"), ("PO11", "CC", "9999.00"), ("PO12", "CA", "500.00"),
        ("PO13", "CB", "600.00"), ("PO15", "CA", "1150.00"), ("PO18", "CD", "400.00"),
        ("PO20", "CF", "1100.00"), ("PO21", "CF", "1200.00"), ("PO22", "CG", "125.00"),
        ("PO23", "CF", "12.01"), ("PO24", "CH", "300.00"),
    ]
    po = []
    for po_line_id, contract_id, committed in po_values:
        po.append({
            **_common(po_rule), "po_line_id": po_line_id, "po_ref": f"ORDER-{po_line_id}",
            "line_number": "1", "program": "OPS", "budget_line_id": "BUDGET",
            "approval_date": "2026-09-01",
            "order_status": "DRAFT" if po_line_id == "PO11" else "APPROVED",
            "currency": "USD", "ordered_qty": "1", "unit_price_native": committed,
            "committed_usd": committed, "obligated_usd": committed if po_line_id != "PO24" else "",
            "obligation_id": f"OB-{po_line_id}" if po_line_id != "PO24" else "",
            "contract_line_id": contract_id,
        })

    contract_values = [
        ("CA", "CA-R1", "2026-09-01", "2026-09-19", "3500.00"),
        ("CA", "CA-R2", "2026-09-20", "2026-10-31", "5000.00"),
        ("CB", "CB-R1", "2026-09-01", "2026-09-21", "5000.00"),
        ("CB", "CB-R2", "2026-09-22", "2026-10-31", "5500.00"),
        ("CC", "CC-R1", "2026-09-01", "2026-10-31", "2000.00"),
        ("CD", "CD-R1", "2026-09-01", "2026-09-30", "1600.00"),
        ("CD", "CD-R2", "2026-10-01", "2026-10-31", "2600.00"),
        ("CF", "CF-R1", "2026-09-01", "2026-10-31", "2200.00"),
        ("CG", "CG-R1", "2026-09-01", "2026-10-31", "200.00"),
        ("CH", "CH-R1", "2026-09-01", "2026-10-31", "500.00"),
    ]
    contract = [{
        **_common(contract_rule), "contract_line_id": contract_id, "revision_id": revision,
        "effective_from": start, "effective_to": end, "currency": "USD",
        "ceiling_usd": ceiling, "contract_reference": f"AWARD-{contract_id}",
    } for contract_id, revision, start, end, ceiling in contract_values]
    return {
        "ledger": (ledger_columns, ledger), "bank": (bank_columns, bank),
        "invoice": (invoice_columns, invoice), "po": (po_columns, po),
        "contract": (contract_columns, contract),
    }


def _field(name, source, *, value_type="string", nullable=False):
    return {
        "name": name, "type": value_type, "nullable": nullable,
        "expression": {"source": source},
    }


def _transform(*fields):
    return {"version": "tabular-transform-v2", "fields": list(fields)}


def calculation_spec():
    return {
        "version": "tabular-relate-v2",
        "datasets": [
            {"alias": alias, "document_id": alias}
            for alias in ("ledger", "bank", "invoice", "po", "contract")
        ],
        "steps": [{
            "id": "posted_cash", "op": "join", "left": "bank", "right": "ledger",
            "how": "left", "cardinality": "many_to_one",
            "on": [{"left": "bank.ledger_posting_id", "right": "ledger.posting_id"}],
        }, {
            "id": "classified", "op": "derive", "input": "posted_cash",
            "transform": _transform({
                "name": "population_status", "type": "string", "nullable": False,
                "expression": {
                    "op": "case",
                    "branches": [
                        {"when": {"op": "eq", "left": {"source": "bank.ledger_posting_id"},
                                  "right": ""}, "then": "unknown_unlinked"},
                        {"when": {"op": "is_null", "value": {
                            "source": "ledger.posting_id",
                        }}, "then": "unknown_missing_ledger"},
                        {"when": {"op": "ne", "left": {"source": "bank.status"},
                                  "right": "SETTLED"}, "then": "excluded_bank_status"},
                        {"when": {"op": "gt", "left": {"source": "bank.settlement_date"},
                                  "right": "2026-10-05", "value_type": "date"},
                         "then": "excluded_evidence_horizon"},
                        {"when": {"op": "ne", "left": {"source": "ledger.status"},
                                  "right": "POSTED"}, "then": "excluded_ledger_status"},
                        {"when": {"op": "lt", "left": {"source": "ledger.posting_date"},
                                  "right": "2026-09-01", "value_type": "date"},
                         "then": "excluded_posting_period"},
                        {"when": {"op": "gt", "left": {"source": "ledger.posting_date"},
                                  "right": "2026-09-30", "value_type": "date"},
                         "then": "excluded_posting_period"},
                    ],
                    "else": "calculation_eligible",
                },
            }),
        }, {
            "id": "allocated", "op": "allocate", "left": "classified", "right": "invoice",
            "on": [{"left": "ledger.invoice_ref", "right": "invoice.invoice_ref"}],
            "event_key": "bank.allocation_id", "detail_key": "invoice.invoice_line_id",
            "amount": "bank.settled_usd", "weight": "invoice.line_amount_native",
            "detail_order": ["invoice.invoice_line_id"], "weight_mode": "absolute",
            "scale": 2, "rounding": "half_up",
        }, {
            "id": "authorized", "op": "join", "left": "allocated", "right": "po",
            "how": "left", "cardinality": "many_to_one",
            "on": [{"left": "invoice.po_line_id", "right": "po.po_line_id"}],
        }, {
            "id": "running", "op": "cumulative_sum", "input": "authorized",
            "partition_by": ["po.contract_line_id"], "order_by": "bank.settlement_date",
            "value": "allocated.allocated_amount",
            "include_when": {"op": "all", "values": [
                {"op": "eq", "left": {"source": "allocated.allocation_status"}, "right": "complete"},
                {"op": "eq", "left": {"source": "classified.population_status"},
                 "right": "calculation_eligible"},
            ]},
            "frame": "unbounded_preceding_through_date_peers",
        }, {
            "id": "dated", "op": "join", "left": "running", "right": "contract",
            "how": "left", "cardinality": "many_to_one",
            "on": [{"left": "po.contract_line_id", "right": "contract.contract_line_id"}],
            "effective": {
                "value": "bank.settlement_date", "start": "contract.effective_from",
                "end": "contract.effective_to", "end_inclusive": True,
            },
        }],
        "result": "dated",
        "output": _transform(
            _field("allocation_id", "bank.allocation_id"),
            _field("invoice_line_id", "invoice.invoice_line_id", nullable=True),
            _field("contract_line_id", "po.contract_line_id", nullable=True),
            _field("settlement_date", "bank.settlement_date", value_type="date"),
            _field("revision_id", "contract.revision_id", nullable=True),
            _field("event_usd", "bank.settled_usd"),
            _field("allocated_usd", "allocated.allocated_amount", nullable=True),
            _field("cumulative_usd", "running.cumulative_value", nullable=True),
            _field("ceiling_usd", "contract.ceiling_usd", nullable=True),
            _field("allocation_status", "allocated.allocation_status"),
            _field("cumulative_status", "running.cumulative_status"),
            _field("population_status", "classified.population_status"),
        ),
    }


def independent_dated_controls(sources):
    from copy import deepcopy

    rows = {alias: deepcopy(values) for alias, (_columns, values) in sources.items()}
    ledger = {
        row["posting_id"]: row for row in rows["ledger"]
        if row["status"] == "POSTED" and "2026-09-01" <= row["posting_date"] <= "2026-09-30"
    }
    invoice = defaultdict(list)
    for row in rows["invoice"]:
        invoice[row["invoice_ref"]].append(row)
    po = {
        row["po_line_id"]: row for row in rows["po"]
        if row["order_status"] == "APPROVED" and row["approval_date"] <= "2026-09-30"
    }
    contracts = defaultdict(list)
    for row in rows["contract"]:
        contracts[row["contract_line_id"]].append(row)
    date_events = defaultdict(lambda: Decimal("0"))
    allocated_parts = []
    for bank in rows["bank"]:
        if bank["status"] != "SETTLED" or bank["settlement_date"] > "2026-10-05":
            continue
        posting = ledger.get(bank["ledger_posting_id"])
        if not posting:
            continue
        lines = sorted(invoice.get(posting["invoice_ref"], ()), key=lambda row: row["invoice_line_id"])
        if not lines:
            continue
        denominator = sum(
            (abs(Decimal(line["line_amount_native"])) for line in lines), Decimal("0"),
        )
        assigned = Decimal("0")
        for index, line in enumerate(lines):
            amount = Decimal(bank["settled_usd"])
            allocated = amount - assigned if index == len(lines) - 1 else (
                amount * abs(Decimal(line["line_amount_native"])) / denominator
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            assigned += allocated
            purchase = po[line["po_line_id"]]
            date_events[(purchase["contract_line_id"], bank["settlement_date"])] += allocated
            allocated_parts.append({
                "allocation_id": bank["allocation_id"], "invoice_line_id": line["invoice_line_id"],
                "contract_line_id": purchase["contract_line_id"],
                "settlement_date": bank["settlement_date"], "allocated_usd": format(allocated, "f"),
            })
    cumulative = defaultdict(lambda: Decimal("0"))
    expected = {}
    for (contract_id, day), amount in sorted(date_events.items()):
        cumulative[contract_id] += amount
        revisions = [
            row for row in contracts[contract_id]
            if row["effective_from"] <= day <= row["effective_to"]
        ]
        assert len(revisions) == 1
        for part in allocated_parts:
            if part["contract_line_id"] == contract_id and part["settlement_date"] == day:
                expected[(part["allocation_id"], part["invoice_line_id"])] = {
                    **part, "cumulative_usd": format(cumulative[contract_id], "f"),
                    "revision_id": revisions[0]["revision_id"],
                    "ceiling_usd": revisions[0]["ceiling_usd"],
                }
    return expected


def test_complete_preparation_and_full_dated_calculation_are_lossless():
    sources = synthetic_sources()
    limits = TabularMergeLimits()
    contexts = []
    for alias, (columns, rows) in sources.items():
        assert len(rows) == {"ledger": 24, "bank": 26, "invoice": 24, "po": 20, "contract": 10}[alias]
        source = TabularMergeSource(alias, f"{alias}.csv", lambda rows=rows, columns=columns: _source_bytes(columns, rows))
        request = {
            "alias": alias, "document_id": alias, "context_columns": list(columns),
            "key_profiles": [{"name": f"{alias}_keys", "columns": [columns[5], columns[-1]]}],
        }
        contexts.append(prepare_tabular_source_context(source, request, limits=limits))
    assert sum(context["physical_row_count"] for context in contexts) == 104
    for context in contexts:
        assert len(context["headers"]) >= 12
        rule = next(
            item["distinct_values"][0]["value"]
            for item in context["context_columns"] if item["column"] == "source_rule"
        )
        assert len(rule) > 500
        assert context["context_columns"][-1]["distinct_values"][0]["rows"]

    datasets = {}
    for selected in calculation_spec()["datasets"]:
        columns, rows = sources[selected["alias"]]
        source = TabularMergeSource(
            selected["document_id"], f"{selected['alias']}.csv",
            lambda columns=columns, rows=rows: _source_bytes(columns, rows),
        )
        datasets[selected["alias"]] = source

    def loader(source):
        def table():
            from functions_tabular_merge import read_tabular_source_records

            return read_tabular_source_records(source, limits=limits)
        return table

    result = calculate_relational_sources(
        calculation_spec(), {alias: loader(source) for alias, source in datasets.items()},
        limits=limits,
    )
    assert result["coverage"]["complete"] is True and result["coverage"]["input_rows"] == 104
    dated = [record for record in result["records"] if record["cumulative_usd"] is not None]
    by_key = defaultdict(list)
    for record in dated:
        by_key[(record["contract_line_id"], record["settlement_date"])].append(record)
    controls = [
        ("CA", "2026-09-07", "3500.00", "4200.00"),
        ("CA", "2026-09-09", "3500.00", "4150.00"),
        ("CB", "2026-09-30", "5500.00", "5900.00"),
        ("CF", "2026-09-26", "2200.00", "2212.02"),
    ]
    for contract_id, day, ceiling, cumulative in controls:
        observations = by_key[(contract_id, day)]
        assert observations and {item["ceiling_usd"] for item in observations} == {ceiling}
        assert {item["cumulative_usd"] for item in observations} == {cumulative}
        excess = Decimal(cumulative) - Decimal(ceiling)
        assert excess > Decimal("0.01")
    october = by_key[("CD", "2026-10-02")]
    assert {item["revision_id"] for item in october} == {"CD-R2"}
    assert {item["cumulative_usd"] for item in october} == {"2500.00"}
    assert {item["ceiling_usd"] for item in october} == {"2600.00"}

    unknown = {
        item["allocation_id"]: item["event_usd"]
        for item in result["records"] if item["allocation_status"] == "unknown_no_detail"
    }
    expected_unknown = {
        row["allocation_id"]: row["settled_usd"]
        for row in sources["bank"][1]
        if not row["ledger_posting_id"]
        or row["ledger_posting_id"] in {
            item["posting_id"] for item in sources["ledger"][1]
            if item["invoice_ref"] not in {line["invoice_ref"] for line in sources["invoice"][1]}
        }
    }
    assert unknown == expected_unknown
    excluded = {
        item["allocation_id"]: item["population_status"]
        for item in result["records"] if item["population_status"].startswith("excluded_")
    }
    expected_excluded = {
        bank_row["allocation_id"]: (
            "excluded_bank_status" if bank_row["status"] != "SETTLED"
            else "excluded_evidence_horizon" if bank_row["settlement_date"] > "2026-10-05"
            else "excluded_ledger_status" if ledger_row["status"] != "POSTED"
            else "excluded_posting_period"
        )
        for bank_row in sources["bank"][1]
        if (ledger_row := next((
            row for row in sources["ledger"][1]
            if row["posting_id"] == bank_row["ledger_posting_id"]
        ), None)) and (
            bank_row["status"] != "SETTLED"
            or bank_row["settlement_date"] > "2026-10-05"
            or ledger_row["status"] != "POSTED"
            or not "2026-09-01" <= ledger_row["posting_date"] <= "2026-09-30"
        )
    }
    assert excluded == expected_excluded
    expected = independent_dated_controls(sources)
    complete = {
        (item["allocation_id"], item.get("invoice_line_id")): item
        for item in result["records"] if (
            item["population_status"] == "calculation_eligible"
            and item["allocation_status"] == "complete"
        )
    }
    assert set(expected) == set(complete)
    for identity, control in expected.items():
        actual = complete[identity]
        assert actual["allocated_usd"] == control["allocated_usd"]
        assert actual["contract_line_id"] == control["contract_line_id"]
        assert actual["settlement_date"] == control["settlement_date"]
        assert actual["cumulative_usd"] == control["cumulative_usd"]
        assert actual["revision_id"] == control["revision_id"]
        assert actual["ceiling_usd"] == control["ceiling_usd"]


def test_preparation_rejects_duplicate_profile_names_before_observations_are_mixed():
    source = TabularMergeSource("keys", "keys.csv", lambda: (
        b"left,right\nk1,k1\nk2,k1\n"
    ))
    request = {
        "alias": "keys", "document_id": "keys",
        "context_columns": ["left", "right"],
        "key_profiles": [
            {"name": "same", "columns": ["left"]},
            {"name": "same", "columns": ["right"]},
        ],
    }
    with pytest.raises(TabularMergeError) as error:
        prepare_tabular_source_context(source, request)
    assert error.value.code == "invalid_options"


def test_preparation_charges_lossless_distinct_value_and_provenance_not_repeated_text():
    repeated = _rule("One exact long rule repeated over every physical row")
    rows = [
        {
            "identifier": f"K{index:03d}", "context": repeated,
            "late_column": "complete" if index == 199 else "present",
        }
        for index in range(200)
    ]
    content = _source_bytes(["identifier", "context", "late_column"], rows)
    source = TabularMergeSource("repeated", "repeated.csv", lambda: content)
    context = prepare_tabular_source_context(source, {
        "alias": "repeated", "document_id": "repeated",
        "context_columns": ["context", "late_column"],
        "key_profiles": [{"name": "keys", "columns": ["identifier"]}],
    })
    rules = context["context_columns"][0]["distinct_values"]
    assert len(rules) == 1 and len(rules[0]["rows"]) == 200
    assert context["key_profiles"][0]["distinct_count"] == 200
    assert sum(context["key_profiles"][0]["multiplicity_counts"]) == 200
    assert context["context_columns"][1]["distinct_values"][-1]["rows"] == [201]
    assert len(content) > 96 * 1024
