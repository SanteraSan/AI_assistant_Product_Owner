from app.services.document_download import (
    archive_filename,
    build_zip_bytes,
    content_disposition,
    unique_entry_names,
)


def test_unique_entry_names_disambiguates_collisions() -> None:
    assert unique_entry_names(["a.md", "a.md", "b.md"]) == ["a.md", "a-2.md", "b.md"]


def test_archive_filename_slugs_bucket_name() -> None:
    assert archive_filename("Aurora Sales Demo") == "aurora-sales-demo-documents.zip"


def test_build_zip_bytes_uses_safe_unique_names() -> None:
    import zipfile
    from io import BytesIO

    payload = build_zip_bytes(
        [
            ("folder/notes.md", b"one"),
            ("notes.md", b"two"),
        ]
    )
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        names = archive.namelist()
        assert "notes.md" in names
        assert "notes-2.md" in names
        assert archive.read("notes.md") == b"one"
        assert archive.read("notes-2.md") == b"two"


def test_content_disposition_keeps_utf8_filename() -> None:
    header = content_disposition("договор.md")
    assert "filename*=" in header
    assert "UTF-8''" in header
