from pathlib import Path

from app.services.document_loader import load_raw_documents
from app.services.sales_demo_data import DEMO_DEAL_SPECS, SALES_DOCUMENT_SPECS


def test_sales_fixture_counts() -> None:
    assert len(DEMO_DEAL_SPECS) == 30
    assert len(SALES_DOCUMENT_SPECS) == 20
    northwind = [item for item in DEMO_DEAL_SPECS if item.bucket_id == "sales_northwind"]
    aurora = [item for item in DEMO_DEAL_SPECS if item.bucket_id == "sales_aurora"]
    assert len(northwind) == 15
    assert len(aurora) == 15


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
