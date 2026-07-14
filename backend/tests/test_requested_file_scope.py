from types import SimpleNamespace

from app.services.requested_file_scope import (
    extract_requested_file_names,
    looks_like_file_inventory_question,
    missing_requested_file_answer,
    resolve_requested_files,
)


def test_extract_requested_file_names_supports_spaces() -> None:
    message = "Расскажи что написано в файле 1000 документов.txt. Этот файл есть в общедоступных"
    assert extract_requested_file_names(message) == ["1000 документов.txt"]


def test_resolve_requested_files_matches_accessible_spaced_name() -> None:
    documents = [
        SimpleNamespace(id="doc-1", file_name="1000 документов.txt", title="1000 документов.txt"),
        SimpleNamespace(id="doc-2", file_name="refactoring.txt", title="refactoring.txt"),
    ]
    resolution = resolve_requested_files(
        message="Что в файле 1000 документов.txt?",
        documents=documents,  # type: ignore[arg-type]
    )
    assert resolution.missing_names == []
    assert [document.id for document in resolution.matched_documents] == ["doc-1"]


def test_resolve_requested_files_refuses_inaccessible_name() -> None:
    documents = [
        SimpleNamespace(id="doc-2", file_name="refactoring.txt", title="refactoring.txt"),
    ]
    resolution = resolve_requested_files(
        message="Расскажи про moto.jpg",
        documents=documents,  # type: ignore[arg-type]
    )
    assert resolution.matched_documents == []
    assert resolution.missing_names == ["moto.jpg"]
    assert "moto.jpg" in missing_requested_file_answer(resolution.missing_names)


def test_looks_like_file_inventory_question() -> None:
    assert looks_like_file_inventory_question("а какие файлы доступны?")
    assert looks_like_file_inventory_question("Список файлов в выбранном bucket")
    assert not looks_like_file_inventory_question("Что написано про CI/CD?")
