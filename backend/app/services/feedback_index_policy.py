FEEDBACK_CLASSES: frozenset[str] = frozenset({"noise", "churn_signal", "bug", "feature"})
PRODUCT_INDEX_CLASSES: frozenset[str] = frozenset({"bug", "feature"})


def feedback_item_enters_product_qdrant(*, feedback_class: str, index_in_rag: bool) -> bool:
    return (
        index_in_rag
        and feedback_class in FEEDBACK_CLASSES
        and feedback_class in PRODUCT_INDEX_CLASSES
    )
