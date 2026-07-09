from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import AreaChart, Reference

from app.services.document_loader import (
    _summarize_excel_chart_xml,
    load_raw_documents,
)


def test_excel_native_chart_loader_builds_chart_evidence(tmp_path: Path) -> None:
    raw_data_dir = tmp_path / "raw"
    raw_data_dir.mkdir()
    workbook_path = raw_data_dir / "charts.xlsx"

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Weight log"
    worksheet.append(["Week", "Weight"])
    worksheet.append(["2026-04-23", 176])
    worksheet.append(["2026-04-30", 175])

    chart = AreaChart()
    chart.add_data(Reference(worksheet, min_col=2, min_row=1, max_row=3), titles_from_data=True)
    chart.set_categories(Reference(worksheet, min_col=1, min_row=2, max_row=3))
    worksheet.add_chart(chart, "D2")
    workbook.save(workbook_path)

    documents = load_raw_documents(raw_data_dir, tenant_id="tenant", bucket_id="bucket")
    chart_documents = [document for document in documents if document.source_type == "excel_chart"]

    assert len(chart_documents) == 1
    assert chart_documents[0].tenant_id == "tenant"
    assert chart_documents[0].bucket_id == "bucket"
    assert "Block type: excel_chart" in chart_documents[0].content
    assert "AreaChart" in chart_documents[0].content
    assert "Weight" in chart_documents[0].content
    assert chart_documents[0].metadata["sheet_name"] == "Weight log"
    assert chart_documents[0].metadata["chart_type"] == "AreaChart"


def test_summarize_excel_chart_xml_extracts_chart_ex_labels() -> None:
    summary = _summarize_excel_chart_xml(
        """
        <cx:chartSpace xmlns:cx="http://schemas.microsoft.com/office/drawing/2014/chartex">
          <cx:series layoutId="clusteredColumn">
            <cx:tx><cx:txData><cx:v>OCCURRENCES</cx:v></cx:txData></cx:tx>
          </cx:series>
          <cx:series layoutId="paretoLine" />
        </cx:chartSpace>
        """
    )

    assert "clusteredColumn" in summary["chart_type"]
    assert "paretoLine" in summary["chart_type"]
    assert "OCCURRENCES" in summary["labels"]
