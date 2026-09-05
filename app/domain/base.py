try:
    from sqlalchemy.orm import declarative_base
    Base = declarative_base()
except Exception as e:
    # Fallback for environments without SQLAlchemy (e.g., synthetic benchmark)
    # Define a minimal placeholder to satisfy type checkers and imports.
    Base = object
    import logging
    logging.getLogger("ariv.domain.base").warning(
        "SQLAlchemy not available or failed to import (%s); using dummy Base.", e
    )
