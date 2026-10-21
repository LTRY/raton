"""The drawing of `/stats`: what the page makes of `GET /api/stats/charts`."""


def monthly_view(monthly: list[dict]) -> dict:
    """What `/stats` draws from the `monthly` window of `GET /api/stats/charts`.

    The API keeps the full 12-month window; the page drops the leading months
    where nothing existed yet, which would otherwise take half the width for
    nothing. Also builds the one-line story, the three key figures and the
    SVG coordinates of the cumulative-storage curve.
    """
    months = [dict(month) for month in monthly]
    while len(months) > 1 and months[0]["cumulative_cards"] == 0:
        months.pop(0)
    current = months[-1]
    previous = months[-2] if len(months) > 1 else None
    window_cards = sum(month["cards_added"] for month in months)

    story = None
    if window_cards:
        if len(months) == 1:
            plural = "s" if window_cards > 1 else ""
            story = f"{window_cards} fiche{plural} ajoutée{plural} en {current['month_name']}."
        else:
            here = (
                f"{current['cards_added']} en {current['month_name']}"
                if current["cards_added"]
                else (f"aucune en {current['month_name']}")
            )
            story = f"{window_cards} fiches ajoutées en {len(months)} mois, dont {here}."

    delta_percent = None
    if previous and previous["cards_added"] > 0:
        delta_percent = round(
            (current["cards_added"] - previous["cards_added"]) / previous["cards_added"] * 100
        )

    peak_bytes = max((month["cumulative_bytes"] for month in months), default=0)
    count = len(months)
    points = []
    for index, month in enumerate(months):
        x = index / (count - 1) * 100 if count > 1 else 100
        y = 100 - (month["cumulative_bytes"] / peak_bytes * 100 if peak_bytes else 0)
        points.append((round(x, 2), round(y, 2)))
    if count == 1:
        points.insert(0, (0, points[0][1]))
    line = " ".join(f"{x},{y}" for x, y in points)

    return {
        "months": months,
        "story": story,
        "current_month_name": current["month_name"],
        "current_cards": current["cards_added"],
        "current_bytes": current["bytes_added"],
        "delta_percent": delta_percent,
        "average_cards": round(window_cards / count) if count else 0,
        "peak_bytes": peak_bytes,
        "curve_line": line,
        "curve_area": f"0,100 {line} 100,100",
        "range_start": f"{months[0]['month_name']} {months[0]['year']}",
    }
