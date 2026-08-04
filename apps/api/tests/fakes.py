from collections.abc import Iterable
from typing import Any


class FakeRows:
    def __init__(self, values: Iterable[Any] = ()) -> None:
        self.values = list(values)

    def all(self) -> list[Any]:
        return self.values

    def first(self) -> Any:
        return self.values[0] if self.values else None

    def mappings(self) -> "FakeRows":
        return self

    def __iter__(self) -> Any:
        return iter(self.values)


class FakeSession:
    def __init__(
        self,
        *,
        scalar_values: Iterable[Any] = (),
        scalar_result_values: Iterable[Iterable[Any]] = (),
        execute_values: Iterable[Iterable[Any]] = (),
        get_values: Iterable[Any] = (),
    ) -> None:
        self.scalar_values = list(scalar_values)
        self.scalar_result_values = list(scalar_result_values)
        self.execute_values = list(execute_values)
        self.get_values = list(get_values)
        self.added: list[Any] = []
        self.commits = 0
        self.rollbacks = 0

    async def scalar(self, statement: Any) -> Any:
        del statement
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def scalars(self, statement: Any) -> FakeRows:
        del statement
        values = self.scalar_result_values.pop(0) if self.scalar_result_values else []
        return FakeRows(values)

    async def execute(self, statement: Any, parameters: Any = None) -> FakeRows:
        del statement, parameters
        values = self.execute_values.pop(0) if self.execute_values else []
        return FakeRows(values)

    async def get(self, model: Any, identifier: Any) -> Any:
        del model, identifier
        return self.get_values.pop(0) if self.get_values else None

    def add(self, value: Any) -> None:
        self.added.append(value)

    def add_all(self, values: Iterable[Any]) -> None:
        self.added.extend(values)

    async def flush(self) -> None:
        for value in self.added:
            if hasattr(value, "id") and getattr(value, "id", None) is None:
                from uuid import uuid4

                value.id = uuid4()

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def refresh(self, value: Any) -> None:
        if hasattr(value, "created_at") and getattr(value, "created_at", None) is None:
            from datetime import UTC, datetime

            value.created_at = datetime.now(UTC)
