from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker


def make_database(url: str) -> tuple[Engine, sessionmaker[Session]]:
    sqlite = url.startswith("sqlite:")
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False, "timeout": 5} if sqlite else {},
        pool_pre_ping=True,
    )
    if sqlite:

        @event.listens_for(engine, "connect")
        def configure(connection: object, _: object) -> None:
            # DBAPI is intentionally isolated from persistence callers.
            cursor = connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine, sessionmaker(engine, expire_on_commit=False)
