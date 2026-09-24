from app.models.chat import SourceChunk
from app.services.hh_resume_sections import (
    prefer_named_resume_employer,
    resume_embedding_parts,
    resume_excerpt,
    split_hh_resume,
)


def test_job_block_keeps_technology_line_from_the_next_page() -> None:
    pages = [
        "Июнь 2023 —\nМай 2025\n2 года\nООО \"ИН РЕВ\"\nТехнологии - React, Electron JS, ChartJs",
        "Июль 2022 —\nИюнь 2023\n1 год\nАО \"БАРС Групп\"\nВедущий Frontend разработчик",
        "Основные технологии проекта\nReact + Redux + TypeScript, Flutter, react-hook-form, AntD UI\nАвгуст 2021 —\nИюль 2022\n1 год\nМир Технологий\nReact + Redux Toolkit",
        "Образование\nУГАТУ\nНавыки\nVue MobX Jest Docker\nОбо мне\nСтек: Next.js",
    ]
    sections = split_hh_resume(pages)
    assert sections is not None
    by_org = {section.organization: section.content for section in sections if section.kind == "employment"}
    assert "Flutter" in by_org['АО "БАРС Групп"']
    assert "ChartJs" in by_org['ООО "ИН РЕВ"']
    assert "Vue" not in by_org['ООО "ИН РЕВ"']
    skills = next(section for section in sections if section.kind == "skills")
    about = next(section for section in sections if section.kind == "about")
    assert "Jest" in skills.content
    assert "Next.js" in about.content
    assert skills.kind == "skills"


def test_plain_pdf_is_not_split_as_resume() -> None:
    assert split_hh_resume(["Договор поставки\nСумма 1000"]) is None


def test_named_employer_drops_skills_and_other_jobs() -> None:
    sources = [
        _source("skills", "", "Vue MobX Jest"),
        _source("employment", 'ООО "ИН РЕВ"', "React, Electron JS, ChartJs"),
        _source("employment", 'АО "БАРС Групп"', "Flutter, AntD UI"),
    ]
    kept = prefer_named_resume_employer('технологии в АО "БАРС Групп"', sources)
    assert [source.content for source in kept] == ["Flutter, AntD UI"]


def test_long_job_stays_embeddable_and_keeps_the_technology_line() -> None:
    body = "Декабрь 2019 —\nАвгуст 2021\n1 год 9 месяцев\n4 организации\n" + ("Обязанности\n" * 400)
    tech = "Основные технологии проекта\nHTML, CSS, JavaScript, ReactJS, Vue, MobX\n"
    parts = resume_embedding_parts(
        body + tech,
        section_kind="employment",
        organization="4 организации",
    )
    assert len(parts) > 1
    assert all(len(part) <= 2200 for part in parts)
    assert all("Vue, MobX" in part for part in parts)


def test_resume_job_excerpt_is_not_cut_at_the_tool_limit() -> None:
    content = "Технологии " + ("React " * 300)
    assert len(resume_excerpt(content, section_kind="employment", limit=800)) > 800


def _source(kind: str, organization: str, content: str) -> SourceChunk:
    return SourceChunk(
        id=kind + organization,
        content=content,
        metadata={"document_metadata": {"resume_section": kind, "organization": organization}},
    )
