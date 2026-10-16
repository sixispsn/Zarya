"""Shared display policy for characteristic residential sections, not geometry AR."""


def representative_floors(count: int) -> tuple[int, ...]:
    if type(count) is not int or not 1 <= count <= 200:
        raise ValueError('Для характерного разреза требуется 1–200 надземных этажей')
    return tuple(range(1, count + 1)) if count <= 3 else (1, 2, count)
