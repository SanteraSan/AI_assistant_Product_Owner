from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.services.sales_scope import SALES_AURORA_BUCKET_ID, SALES_NORTHWIND_BUCKET_ID

GOLD_NW_104_CARD_AMOUNT = 1_250_000
GOLD_NW_104_CONTRACT_AMOUNT = 1_180_000
GOLD_AU_207_CARD_CLOSE = date(2026, 11, 1)
GOLD_AU_207_CONTRACT_CLOSE = date(2026, 12, 15)
GOLD_NW_110_CARD_STATUS = "signed"
AURORA_LEAK_MARKERS = ("Aurora Polar Rebate", "777000")


@dataclass(frozen=True)
class DemoDealSpec:
    bucket_id: str
    deal_code: str
    title: str
    amount: int
    close_date: date
    status: str
    owner: str
    aliases: tuple[str, ...] = ()
    currency: str = "RUB"


@dataclass(frozen=True)
class SalesDocumentSpec:
    relative_path: str
    bucket_id: str
    source_type: str
    body: str
    features: tuple[str, ...] = ("sales",)
    metadata: dict[str, object] = field(default_factory=dict)


DEMO_DEAL_SPECS: tuple[DemoDealSpec, ...] = (
    DemoDealSpec(
        SALES_NORTHWIND_BUCKET_ID,
        "nw-101",
        "CRM Starter",
        320_000,
        date(2026, 8, 1),
        "signed",
        "Anna Petrova",
        ("northwind-101",),
    ),
    DemoDealSpec(
        SALES_NORTHWIND_BUCKET_ID,
        "nw-102",
        "Support retainer",
        180_000,
        date(2026, 9, 15),
        "proposed",
        "Anna Petrova",
    ),
    DemoDealSpec(
        SALES_NORTHWIND_BUCKET_ID,
        "nw-103",
        "Warehouse WMS",
        760_000,
        date(2026, 10, 1),
        "negotiation",
        "Igor Sokolov",
    ),
    DemoDealSpec(
        SALES_NORTHWIND_BUCKET_ID,
        "nw-104",
        "Enterprise CRM rollout",
        GOLD_NW_104_CARD_AMOUNT,
        date(2026, 10, 20),
        "proposed",
        "Anna Petrova",
        ("northwind-104",),
    ),
    DemoDealSpec(
        SALES_NORTHWIND_BUCKET_ID,
        "nw-105",
        "Analytics add-on",
        210_000,
        date(2026, 7, 12),
        "signed",
        "Igor Sokolov",
    ),
    DemoDealSpec(
        SALES_NORTHWIND_BUCKET_ID,
        "nw-106",
        "Mobile app pack",
        540_000,
        date(2026, 6, 30),
        "lost",
        "Anna Petrova",
    ),
    DemoDealSpec(
        SALES_NORTHWIND_BUCKET_ID,
        "nw-107",
        "Training bundle",
        95_000,
        date(2026, 8, 20),
        "signed",
        "Maria Orlova",
    ),
    DemoDealSpec(
        SALES_NORTHWIND_BUCKET_ID,
        "nw-108",
        "MSA renewal",
        410_000,
        date(2026, 11, 5),
        "negotiation",
        "Anna Petrova",
        ("northwind-108",),
    ),
    DemoDealSpec(
        SALES_NORTHWIND_BUCKET_ID,
        "nw-109",
        "Data migration",
        290_000,
        date(2026, 9, 28),
        "proposed",
        "Igor Sokolov",
    ),
    DemoDealSpec(
        SALES_NORTHWIND_BUCKET_ID,
        "nw-110",
        "Legal letter pack",
        430_000,
        date(2026, 10, 8),
        GOLD_NW_110_CARD_STATUS,
        "Maria Orlova",
        ("northwind-110",),
    ),
    DemoDealSpec(
        SALES_NORTHWIND_BUCKET_ID,
        "nw-111",
        "Helpdesk SLA",
        150_000,
        date(2026, 7, 1),
        "signed",
        "Anna Petrova",
    ),
    DemoDealSpec(
        SALES_NORTHWIND_BUCKET_ID,
        "nw-112",
        "BI dashboard",
        670_000,
        date(2026, 11, 12),
        "proposed",
        "Igor Sokolov",
    ),
    DemoDealSpec(
        SALES_NORTHWIND_BUCKET_ID,
        "nw-113",
        "Partner portal",
        880_000,
        date(2026, 12, 1),
        "negotiation",
        "Anna Petrova",
    ),
    DemoDealSpec(
        SALES_NORTHWIND_BUCKET_ID,
        "nw-114",
        "Q4 upsell",
        125_000,
        date(2026, 10, 31),
        "draft",
        "Maria Orlova",
    ),
    DemoDealSpec(
        SALES_NORTHWIND_BUCKET_ID,
        "nw-115",
        "Onboarding kit",
        78_000,
        date(2026, 8, 5),
        "signed",
        "Anna Petrova",
    ),
    DemoDealSpec(
        SALES_AURORA_BUCKET_ID,
        "au-201",
        "Polar Rebate program",
        777_000,
        date(2026, 8, 10),
        "signed",
        "Elena Volkova",
        ("aurora-201",),
    ),
    DemoDealSpec(
        SALES_AURORA_BUCKET_ID,
        "au-202",
        "Storefront starter",
        240_000,
        date(2026, 9, 1),
        "proposed",
        "Elena Volkova",
    ),
    DemoDealSpec(
        SALES_AURORA_BUCKET_ID,
        "au-203",
        "Loyalty engine",
        510_000,
        date(2026, 10, 15),
        "negotiation",
        "Pavel Morozov",
    ),
    DemoDealSpec(
        SALES_AURORA_BUCKET_ID,
        "au-204",
        "Inventory sync",
        330_000,
        date(2026, 7, 22),
        "signed",
        "Elena Volkova",
    ),
    DemoDealSpec(
        SALES_AURORA_BUCKET_ID,
        "au-205",
        "POS upgrade",
        460_000,
        date(2026, 11, 20),
        "proposed",
        "Pavel Morozov",
    ),
    DemoDealSpec(
        SALES_AURORA_BUCKET_ID,
        "au-206",
        "Warehouse cameras",
        190_000,
        date(2026, 6, 18),
        "lost",
        "Elena Volkova",
    ),
    DemoDealSpec(
        SALES_AURORA_BUCKET_ID,
        "au-207",
        "Storefront analytics pack",
        890_000,
        GOLD_AU_207_CARD_CLOSE,
        "proposed",
        "Elena Volkova",
        ("aurora-207",),
    ),
    DemoDealSpec(
        SALES_AURORA_BUCKET_ID,
        "au-208",
        "Franchise pack",
        1_200_000,
        date(2026, 12, 10),
        "negotiation",
        "Pavel Morozov",
        ("aurora-208",),
    ),
    DemoDealSpec(
        SALES_AURORA_BUCKET_ID,
        "au-209",
        "Seasonal campaign",
        175_000,
        date(2026, 8, 28),
        "signed",
        "Elena Volkova",
    ),
    DemoDealSpec(
        SALES_AURORA_BUCKET_ID,
        "au-210",
        "Delivery slots",
        265_000,
        date(2026, 9, 20),
        "proposed",
        "Pavel Morozov",
    ),
    DemoDealSpec(
        SALES_AURORA_BUCKET_ID,
        "au-211",
        "Gift cards",
        88_000,
        date(2026, 7, 5),
        "signed",
        "Elena Volkova",
    ),
    DemoDealSpec(
        SALES_AURORA_BUCKET_ID,
        "au-212",
        "Marketplace listing",
        640_000,
        date(2026, 10, 25),
        "negotiation",
        "Pavel Morozov",
    ),
    DemoDealSpec(
        SALES_AURORA_BUCKET_ID,
        "au-213",
        "Night shift SLA",
        142_000,
        date(2026, 11, 8),
        "draft",
        "Elena Volkova",
    ),
    DemoDealSpec(
        SALES_AURORA_BUCKET_ID,
        "au-214",
        "Cold chain sensors",
        355_000,
        date(2026, 12, 2),
        "proposed",
        "Pavel Morozov",
    ),
    DemoDealSpec(
        SALES_AURORA_BUCKET_ID,
        "au-215",
        "HQ reporting",
        920_000,
        date(2026, 8, 14),
        "signed",
        "Elena Volkova",
    ),
)


SALES_DOCUMENT_SPECS: tuple[SalesDocumentSpec, ...] = (
    SalesDocumentSpec(
        "sales_northwind/northwind-overview.md",
        SALES_NORTHWIND_BUCKET_ID,
        "sales_note",
        """# Northwind Traders — кабинет сделок

Это синтетический кабинет Northwind. Здесь живут сделки nw-101 … nw-115.

Правило кабинета: сумма и статус в CRM-карточке могут расходиться с договором.
Не подмешивай данные другого кабинета.
""",
        metadata={"cabinet": "northwind"},
    ),
    SalesDocumentSpec(
        "sales_northwind/northwind-playbook.md",
        SALES_NORTHWIND_BUCKET_ID,
        "sales_playbook",
        """# Northwind playbook

Если рядом есть карточка сделки и текст договора, сравни слои отдельно.
Не утверждай, что письмо отправлено, пока в документах нет факта отправки.
""",
        metadata={"cabinet": "northwind"},
    ),
    SalesDocumentSpec(
        "sales_northwind/northwind-pricing.md",
        SALES_NORTHWIND_BUCKET_ID,
        "sales_note",
        """# Northwind pricing notes

Типовые пакеты кабинета:

- CRM Starter — ориентир 320000 RUB
- Helpdesk SLA — ориентир 150000 RUB
- Onboarding kit — ориентир 78000 RUB

Сумма конкретного договора всегда важнее этой шпаргалки.
""",
        metadata={"cabinet": "northwind"},
    ),
    SalesDocumentSpec(
        "sales_northwind/nw-104-contract.md",
        SALES_NORTHWIND_BUCKET_ID,
        "sales_contract",
        """# Договор nw-104 — Enterprise CRM rollout

Стороны: Northwind Traders и клиент Contoso Plants.

Предмет: поэтапный rollout CRM.

Сумма договора: 1180000 RUB.

Плановая дата закрытия по договору: 20 октября 2026 (2026-10-20).

Оплата: два этапа, без премий за досрочный запуск.
""",
        metadata={"cabinet": "northwind", "deal_code": "nw-104"},
    ),
    SalesDocumentSpec(
        "sales_northwind/nw-104-email.md",
        SALES_NORTHWIND_BUCKET_ID,
        "sales_email",
        """# Внутренняя переписка по nw-104

Тема: уточнение объёма внедрения Enterprise CRM rollout.

Юристы просят не обещать расширенный модуль аналитики до отдельного приложения.
Про сумму в этом письме не договаривались — смотрите подписанный договор.
""",
        metadata={"cabinet": "northwind", "deal_code": "nw-104"},
    ),
    SalesDocumentSpec(
        "sales_northwind/nw-110-draft-letter.md",
        SALES_NORTHWIND_BUCKET_ID,
        "sales_email",
        """# Черновик юридического письма по nw-110

Код сделки: nw-110.
Название: Legal letter pack.

Это черновик. Письмо ещё не отправлено клиенту.
Ответственный: Maria Orlova.
Нельзя писать клиенту, что пакет уже направлен.
""",
        metadata={"cabinet": "northwind", "deal_code": "nw-110"},
    ),
    SalesDocumentSpec(
        "sales_northwind/nw-101-contract.md",
        SALES_NORTHWIND_BUCKET_ID,
        "sales_contract",
        """# Договор nw-101 — CRM Starter

Сумма договора: 320000 RUB.
Статус по договору: подписан.
Дата закрытия: 1 августа 2026.
""",
        metadata={"cabinet": "northwind", "deal_code": "nw-101"},
    ),
    SalesDocumentSpec(
        "sales_northwind/nw-108-msa.md",
        SALES_NORTHWIND_BUCKET_ID,
        "sales_contract",
        """# MSA renewal nw-108

Рамочное соглашение на 410000 RUB.
Срок обсуждения: до 5 ноября 2026.
Статус: переговоры, подписи нет.
""",
        metadata={"cabinet": "northwind", "deal_code": "nw-108"},
    ),
    SalesDocumentSpec(
        "sales_northwind/northwind-legal.md",
        SALES_NORTHWIND_BUCKET_ID,
        "sales_note",
        """# Northwind legal notes

Черновик письма не равен отправке.
Подпись в карточке CRM не заменяет файл договора.
""",
        metadata={"cabinet": "northwind"},
    ),
    SalesDocumentSpec(
        "sales_northwind/northwind-renewal.md",
        SALES_NORTHWIND_BUCKET_ID,
        "sales_playbook",
        """# Northwind renewal checklist

Для MSA renewal сверьте карточку nw-108 с текстом рамочного соглашения.
Не используйте суммы других сделок как подсказку.
""",
        metadata={"cabinet": "northwind"},
    ),
    SalesDocumentSpec(
        "sales_aurora/aurora-overview.md",
        SALES_AURORA_BUCKET_ID,
        "sales_note",
        """# Aurora Retail — кабинет сделок

Синтетический кабинет Aurora. Сделки au-201 … au-215.
Отдельная программа кабинета: Aurora Polar Rebate.
Не смешивать с кабинетом Northwind.
""",
        metadata={"cabinet": "aurora"},
    ),
    SalesDocumentSpec(
        "sales_aurora/aurora-playbook.md",
        SALES_AURORA_BUCKET_ID,
        "sales_playbook",
        """# Aurora playbook

Сравнивайте дату в карточке и дату в договоре отдельно.
Сезонные кампании не переносят дату analytics-пакета.
""",
        metadata={"cabinet": "aurora"},
    ),
    SalesDocumentSpec(
        "sales_aurora/aurora-pricing.md",
        SALES_AURORA_BUCKET_ID,
        "sales_note",
        """# Aurora pricing notes

- Storefront starter — 240000 RUB
- Gift cards — 88000 RUB
- Delivery slots — 265000 RUB
""",
        metadata={"cabinet": "aurora"},
    ),
    SalesDocumentSpec(
        "sales_aurora/au-207-contract.md",
        SALES_AURORA_BUCKET_ID,
        "sales_contract",
        """# Договор au-207 — Storefront analytics pack

Сумма договора: 890000 RUB.

Дата закрытия по договору: 15 декабря 2026 (2026-12-15).

Состав: витрина отчётов, без модуля камер и без franchise pack.
""",
        metadata={"cabinet": "aurora", "deal_code": "au-207"},
    ),
    SalesDocumentSpec(
        "sales_aurora/au-207-email.md",
        SALES_AURORA_BUCKET_ID,
        "sales_email",
        """# Переписка по au-207

Клиент просит не стартовать внедрение до согласования витрины отчётов.
Про перенос даты в этом письме решения нет — ориентир только договор.
""",
        metadata={"cabinet": "aurora", "deal_code": "au-207"},
    ),
    SalesDocumentSpec(
        "sales_aurora/au-201-rebate.md",
        SALES_AURORA_BUCKET_ID,
        "sales_contract",
        """# Программа Aurora Polar Rebate — au-201

Название программы: Aurora Polar Rebate.
Сумма: 777000 RUB.
Статус: подписана 10 августа 2026.
Это внутренний маркер кабинета Aurora, его не должно быть в ответах Northwind.
""",
        metadata={"cabinet": "aurora", "deal_code": "au-201"},
    ),
    SalesDocumentSpec(
        "sales_aurora/au-208-franchise.md",
        SALES_AURORA_BUCKET_ID,
        "sales_contract",
        """# Franchise pack au-208

Сумма: 1200000 RUB.
Статус: переговоры.
Дата обсуждения: 10 декабря 2026.
""",
        metadata={"cabinet": "aurora", "deal_code": "au-208"},
    ),
    SalesDocumentSpec(
        "sales_aurora/aurora-legal.md",
        SALES_AURORA_BUCKET_ID,
        "sales_note",
        """# Aurora legal notes

Карточка CRM и договор — разные слои.
Программа Aurora Polar Rebate относится только к этому кабинету.
""",
        metadata={"cabinet": "aurora"},
    ),
    SalesDocumentSpec(
        "sales_aurora/aurora-seasonal.md",
        SALES_AURORA_BUCKET_ID,
        "sales_note",
        """# Aurora seasonal campaign

Кампания au-209 на 175000 RUB уже подписана.
Она не меняет дату analytics pack au-207.
""",
        metadata={"cabinet": "aurora"},
    ),
    SalesDocumentSpec(
        "sales_aurora/au-212-marketplace.md",
        SALES_AURORA_BUCKET_ID,
        "sales_contract",
        """# Marketplace listing au-212

Сумма: 640000 RUB.
Статус: переговоры.
Дата: 25 октября 2026.
""",
        metadata={"cabinet": "aurora", "deal_code": "au-212"},
    ),
)


SALES_BUCKET_SEED = (
    (SALES_NORTHWIND_BUCKET_ID, "Northwind Sales Demo", "Synthetic Northwind sales cabinet"),
    (SALES_AURORA_BUCKET_ID, "Aurora Sales Demo", "Synthetic Aurora sales cabinet"),
)
