from pathlib import Path

from app.services.document_loader import load_raw_documents
from app.services.sales_demo_data import AURORA_LEAK_MARKERS, DEMO_DEAL_SPECS, SALES_DOCUMENT_SPECS

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"
NW_110_FORBIDDEN = ("уже отправлено", "уже направлено", "письмо отправлено клиенту")


def _cabinet_text(prefix: str) -> str:
    return "\n".join(
        (RAW_DIR / spec.relative_path).read_text(encoding="utf-8")
        for spec in SALES_DOCUMENT_SPECS
        if spec.relative_path.startswith(prefix)
    )


def test_sales_fixture_counts() -> None:
    assert len(DEMO_DEAL_SPECS) == 30
    assert len(SALES_DOCUMENT_SPECS) == 22
    northwind = [item for item in DEMO_DEAL_SPECS if item.bucket_id == "sales_northwind"]
    aurora = [item for item in DEMO_DEAL_SPECS if item.bucket_id == "sales_aurora"]
    assert len(northwind) == 15
    assert len(aurora) == 15
    assert {spec.relative_path for spec in SALES_DOCUMENT_SPECS} >= {
        "sales_northwind/nw-104-appendix.md",
        "sales_aurora/au-207-spec-table.md",
    }


def test_sales_document_files_exist() -> None:
    for spec in SALES_DOCUMENT_SPECS:
        assert (RAW_DIR / spec.relative_path).is_file(), spec.relative_path


def test_gold_facts_stay_on_the_right_layer() -> None:
    contract = (RAW_DIR / "sales_northwind/nw-104-contract.md").read_text(encoding="utf-8")
    appendix = (RAW_DIR / "sales_northwind/nw-104-appendix.md").read_text(encoding="utf-8")
    email = (RAW_DIR / "sales_northwind/nw-104-email.md").read_text(encoding="utf-8")
    draft = (RAW_DIR / "sales_northwind/nw-110-draft-letter.md").read_text(encoding="utf-8")
    au_contract = (RAW_DIR / "sales_aurora/au-207-contract.md").read_text(encoding="utf-8")
    au_spec = (RAW_DIR / "sales_aurora/au-207-spec-table.md").read_text(encoding="utf-8")

    for layer in (contract, appendix):
        assert "1180000" in layer.replace(" ", "")
        assert "1180000" in layer[:1800].replace(" ", "")
        assert "1 250 000" not in layer
        assert "1250000" not in layer.replace(" ", "")

    assert "1 250 000" in email
    assert "1180000" not in email.replace(" ", "")
    assert "1 180 000" not in email

    assert "письмо не отправлено" in draft.lower()
    for marker in NW_110_FORBIDDEN:
        assert marker not in draft.lower()

    assert "2026-12-15" in au_contract
    assert "2026-12-15" in au_contract[:1800]
    assert "2026-12-15" in au_spec
    assert "2026-12-15" in au_spec[:1800]
    assert "2026-11-01" not in au_contract
    assert "2026-11-01" not in au_spec


def test_northwind_files_have_no_aurora_leak_markers() -> None:
    text = _cabinet_text("sales_northwind/")
    lowered = text.lower()
    assert "aurora polar rebate" not in lowered
    assert "777000" not in text.replace(" ", "")
    assert "777 000" not in text
    assert "au-201" not in lowered


def test_aurora_files_have_no_nw104_gold_amounts() -> None:
    text = _cabinet_text("sales_aurora/")
    compact = text.replace(" ", "")
    assert "nw-104" not in text.lower()
    assert "1250000" not in compact
    assert "1180000" not in compact
    assert "1 250 000" not in text
    assert "1 180 000" not in text


def test_playbook_avoids_gold_forbidden_substrings() -> None:
    playbook = (RAW_DIR / "sales_northwind/northwind-playbook.md").read_text(encoding="utf-8")
    for marker in NW_110_FORBIDDEN:
        assert marker not in playbook.lower()


def test_sales_manifest_marks_synthetic(tmp_path: Path) -> None:
    relative = SALES_DOCUMENT_SPECS[0].relative_path
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    target.write_text(SALES_DOCUMENT_SPECS[0].body, encoding="utf-8")
    (tmp_path / "ingestion_manifest.json").write_text(
        """
{
  "documents": [
    {
      "path": "%s",
      "tenant_id": "local_demo",
      "bucket_id": "sales_northwind",
      "source_type": "sales_note",
      "features": ["sales"],
      "metadata": {"synthetic": true, "cabinet": "northwind"}
    }
  ]
}
"""
        % relative,
        encoding="utf-8",
    )
    documents = load_raw_documents(tmp_path)
    assert len(documents) == 1
    assert documents[0].bucket_id == "sales_northwind"
    assert documents[0].source_type == "sales_note"
    assert documents[0].feature == ["sales"]
    assert documents[0].metadata.get("synthetic") is True
