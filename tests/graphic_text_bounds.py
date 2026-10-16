"""Physical text bounds, including the frame's explicit external columns."""

import pymupdf


def assert_graphic_text_bounds(page, width, height, paper):
    mm = 72 / 25.4

    def rect(values):
        return pymupdf.Rect(*(v * mm for v in values))

    assert abs(page.rect.width / mm - width) < .01
    assert abs(page.rect.height / mm - height) < .01
    body = rect((20, 5, width - 5, height - 5))
    bottom = height - 5
    external = [
        (rect((8, bottom - 85, 13, bottom - 60)), "Взам.инв.№"),
        (rect((8, bottom - 60, 13, bottom - 25)), "Подп.идата"),
        (rect((8, bottom - 25, 13, bottom)), "Инв.№подл."),
        (rect((width - 35, height - 5, width - 5, height)), "Формат" + paper),
    ]
    found = ["" for _ in external]
    for word in page.get_text("words"):
        bounds = pymupdf.Rect(word[:4])
        assert page.rect.contains(bounds), word
        if body.contains(bounds):
            continue
        for index, (region, labels) in enumerate(external):
            if region.contains(bounds) and word[4] in labels:
                found[index] += word[4]
                break
        else:
            raise AssertionError(word)
    assert found == [labels for _, labels in external]
