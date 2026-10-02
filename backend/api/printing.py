"""Print readiness for the photo book.

A5 pages leave about 128 mm for a full-width photo. 300 dpi is the usual print target;
below about 150 dpi most people notice blur, which is common for old prints shot with a
phone and for small digital files.
"""

PRINT_WIDTH_MM = 128
GOOD_DPI = 250
ACCEPTABLE_DPI = 150


def print_quality(width, height):
    """Rating for printing the photo across the page, or None when the size is unknown."""
    if not width or not height:
        return None
    dpi = round(max(width, height) / (PRINT_WIDTH_MM / 25.4))
    if dpi >= GOOD_DPI:
        rating = "good"
    elif dpi >= ACCEPTABLE_DPI:
        rating = "acceptable"
    else:
        rating = "low"
    return {"rating": rating, "dpi": dpi}
