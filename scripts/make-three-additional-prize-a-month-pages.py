# scripts/make-three-additional-prize-a-month-pages.py
#
# Requires the preceding prize-page patches, including:
#   implement-design-for-prize-a-month-feature.py
#
# Adds:
#   - Prize a Month — Stallions
#   - Prize a Month — Breeding Farms
#   - Prize a Month — Checklist Criteria
#
# Reuses the installed dark chart design and date-period options.
# New charts default to 50 bars per view.
#
# Criteria attribution:
#   Each checked criterion receives the full checklist prize once.
#   Overlapping criteria are not treated as mutually exclusive.
#   Totals/counts are labeled and explained accordingly.
#
# Preserves existing comparison functions and other page content.
# Updates navigation and enables the new pages in an existing
# conditional wide-layout configuration, where applicable.
#
# Creates a timestamped source backup.
# Does not modify database records or schema.
#
# Stop Streamlit before running:
#
# python scripts/make-three-additional-prize-a-month-pages.py app.py

RUNTIME = r'''
# THREE_ADDITIONAL_PRIZE_PAGES_V1

_MPX_PERIODS = __PERIODS__

_MPX_CONFIG = {
    "stallion": (
        "Stallion",
        "Stallions",
        "stallions",
        "stallion_name",
        "stallion_id",
    ),
    "breedingfarm": (
        "Breeding Farm",
        "Breeding Farms",
        "breeding_farms",
        "breeding_farm_name",
        "breeding_farm_id",
    ),
    "criteria": (
        "Checklist Criterion",
        "Checklist Criteria",
        "criteria",
        "criteria_name",
        None,
    ),
}


def _mpx_labels(rows):
    from collections import Counter

    cleaned = [
        (row["id"], str(row["name"]).strip())
        for row in rows
        if row["name"] is not None
        and str(row["name"]).strip()
    ]

    counts = Counter(name for _, name in cleaned)
    result, used = {}, set()

    for key, name in cleaned:
        candidate = (
            name
            if counts[name] == 1
            else f"{name} [#{key}]"
        )

        while candidate in used:
            candidate += f" [#{key}]"

        result[key] = candidate
        used.add(candidate)

    return result


def _mpx_fetch(owner_id, kind):
    _, _, table, column, field = _MPX_CONFIG[kind]

    conn = get_db_connection()

    try:
        refs = [
            dict(row)
            for row in conn.execute(
                f'SELECT id, "{column}" AS name '
                f'FROM "{table}" '
                'WHERE owner_id = ? '
                f'ORDER BY "{column}" COLLATE NOCASE, id',
                (owner_id,),
            ).fetchall()
        ]

        venues = [
            dict(row)
            for row in conn.execute(
                'SELECT id, venue_name AS name '
                'FROM venues WHERE owner_id = ?',
                (owner_id,),
            ).fetchall()
        ]

        reference = f'"{field}"' if field else "NULL"

        records = [
            dict(row)
            for row in conn.execute(
                'SELECT id, date_of_race, prize, venue_id, '
                f'checklist, {reference} AS reference_id '
                'FROM checklists WHERE owner_id = ?',
                (owner_id,),
            ).fetchall()
        ]

    finally:
        conn.close()

    return (
        _mpx_labels(refs),
        {
            row["id"]: str(row["name"])
            for row in refs
            if row["name"] is not None
        },
        _mpx_labels(venues),
        records,
    )


def _mpx_checked(value):
    if isinstance(value, str):
        return value.strip().casefold() in {
            "1", "true", "t", "yes", "y", "on", "checked",
        }

    return (
        value is True
        or (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and value == 1
        )
    )


def _mpx_prepare(
    records,
    refs,
    raw_names,
    venues,
    chosen,
    first,
    end,
    kind,
):
    import json
    import math
    from collections import defaultdict

    selected = set(chosen)
    values = defaultdict(list)
    counts = defaultdict(int)

    stats = {
        "valid": 0,
        "missing": 0,
        "invalid": 0,
        "invalid_dates": 0,
    }

    criterion_ids = (
        {
            raw_names[key]: key
            for key in selected
        }
        if kind == "criteria"
        else {}
    )

    for record in records:
        if kind == "criteria":
            saved = record.get("checklist")

            if isinstance(saved, str):
                try:
                    saved = json.loads(saved)
                except (ValueError, TypeError):
                    saved = {}

            if not isinstance(saved, dict):
                saved = {}

            matched = [
                criterion_ids[name]
                for name, value in saved.items()
                if name in criterion_ids
                and _mpx_checked(value)
            ]

        else:
            key = record.get("reference_id")
            matched = [key] if key in selected else []

        if not matched:
            continue

        racedate = parse_race_date(
            record.get("date_of_race")
        )

        if racedate is None:
            stats["invalid_dates"] += len(matched)
            continue

        if not first <= racedate < end:
            continue

        raw_prize = record.get("prize")

        if (
            raw_prize is None
            or (
                isinstance(raw_prize, str)
                and not raw_prize.strip()
            )
        ):
            stats["missing"] += len(matched)
            continue

        try:
            if isinstance(raw_prize, bool):
                raise ValueError("Boolean prize")

            prize = float(raw_prize)

            if not math.isfinite(prize) or prize < 0:
                raise ValueError("Invalid prize")

        except (TypeError, ValueError, OverflowError):
            stats["invalid"] += len(matched)
            continue

        venue = venues.get(
            record.get("venue_id"),
            "(No venue)",
        )

        for key in matched:
            values[key, venue].append(prize)
            counts[key, venue] += 1
            stats["valid"] += 1

    amounts = {
        key: math.fsum(items)
        for key, items in values.items()
    }

    total_parts = defaultdict(list)

    for (key, _), amount in amounts.items():
        total_parts[key].append(amount)

    totals = {
        key: math.fsum(total_parts[key])
        for key in chosen
    }

    grand_total = math.fsum(totals.values())

    if not math.isfinite(grand_total):
        raise ValueError(
            "The recorded prize total exceeds "
            "the supported numeric range."
        )

    order = sorted(
        chosen,
        key=lambda key: (
            -totals[key],
            refs[key].casefold(),
            key,
        ),
    )

    venue_order = sorted(
        {
            venue
            for _, venue in amounts
        },
        key=lambda value: (
            value.casefold(),
            value,
        ),
    )

    stats.update(
        total=grand_total,
        venues=len(venue_order),
        entity_order=[
            refs[key]
            for key in order
        ],
        venue_order=venue_order,
    )

    label = _MPX_CONFIG[kind][0]

    total_column = (
        "Attributed Prize (JPY)"
        if kind == "criteria"
        else "Total Prize (JPY)"
    )

    count_column = (
        "Criterion matches"
        if kind == "criteria"
        else "Valid-prize checklists"
    )

    chart_rows = []
    table_rows = []

    for key in order:
        table_row = {
            label: refs[key],
            total_column: totals[key],
            count_column: sum(
                counts[key, venue]
                for venue in venue_order
            ),
        }

        for venue in venue_order:
            amount = amounts.get(
                (key, venue),
                0.0,
            )

            table_row[f"Venue: {venue}"] = amount

            if (key, venue) in amounts:
                chart_rows.append(
                    {
                        "entity": refs[key],
                        "venue": venue,
                        "prize": amount,
                        "entity_total": totals[key],
                        "checklists": counts[key, venue],
                    }
                )

        table_rows.append(table_row)

    return chart_rows, table_rows, stats


def _mpx_page(kind):
    import calendar
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    import pandas as pd

    owner_id = st.session_state.user_id
    label, plural, _, _, _ = _MPX_CONFIG[kind]
    prefix = f"mpx_{kind}_{owner_id}_"

    st.header(f"Prize a Month — {plural}")

    now = datetime.now(
        ZoneInfo("Asia/Tokyo")
    )

    first_col, second_col = st.columns(2)

    with first_col:
        year = int(
            st.number_input(
                "Year",
                min_value=1980,
                max_value=2100,
                value=now.year,
                step=1,
                key=prefix + "year",
            )
        )

    with second_col:
        month = int(
            st.selectbox(
                "Month",
                list(range(1, 13)),
                index=now.month - 1,
                format_func=lambda number: (
                    calendar.month_name[number]
                ),
                key=prefix + "month",
            )
        )

    period = st.radio(
        "Data period",
        _MPX_PERIODS,
        horizontal=True,
        key=prefix + "period",
    )

    refs, raw_names, venues, records = _mpx_fetch(
        owner_id,
        kind,
    )

    if not refs:
        st.info(
            f"No {plural.lower()} are registered "
            "for this account."
        )
        return

    options = sorted(
        refs,
        key=lambda key: (
            refs[key].casefold(),
            key,
        ),
    )

    choices = st.multiselect(
        f"Compare {plural.lower()}",
        [None] + options,
        default=[None],
        format_func=lambda key: (
            f"All {plural.lower()}"
            if key is None
            else refs[key]
        ),
        key=prefix + "selection",
        help=(
            "All includes every registered item. "
            "Remove All to compare only individually "
            "selected items."
        ),
    )

    chosen = (
        options
        if None in choices
        else choices
    )

    if not chosen:
        st.info(
            f"Select at least one {label.lower()}."
        )
        return

    first, end = _mp_dates(
        year,
        month,
        period,
    )

    try:
        chart_rows, table_rows, stats = _mpx_prepare(
            records,
            refs,
            raw_names,
            venues,
            chosen,
            first,
            end,
            kind,
        )

    except (ValueError, OverflowError) as error:
        st.error(str(error))
        return

    chart = (
        _mpx_criteria_chart
        if kind == "criteria"
        else _mpx_chart
    )

    chart(
        chart_rows,
        stats,
        label,
        kind,
        year,
        month,
        period=period,
    )

    st.subheader("Venue breakdown")

    table = pd.DataFrame(table_rows)

    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        height=480,
    )

    last = end - timedelta(days=1)

    st.download_button(
        "Download comparison CSV",
        data=table.to_csv(
            index=False
        ).encode("utf-8-sig"),
        file_name=(
            f"prize_{kind}_"
            f"{first.isoformat()}_to_"
            f"{last.isoformat()}.csv"
        ),
        mime="text/csv",
        key=prefix + "csv",
    )

'''

import argparse
import ast
import copy
from datetime import datetime
from pathlib import Path
import re
import shutil
import tempfile


MARKER = "# THREE_ADDITIONAL_PRIZE_PAGES_V1"

PAGES = {
    "Prize a Month — Stallions": "stallion",
    "Prize a Month — Breeding Farms": "breedingfarm",
    "Prize a Month — Checklist Criteria": "criteria",
}


def function(tree, name):
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == name
    ]

    if len(matches) != 1:
        raise ValueError(
            f"Expected one {name}; "
            f"found {len(matches)}."
        )

    return matches[0]


def start_line(node):
    return min(
        [node.lineno]
        + [
            decorator.lineno
            for decorator in node.decorator_list
        ]
    ) - 1


def html_node(chart):
    found = [
        node.value
        for node in ast.walk(chart)
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "html"
                for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
    ]

    if len(found) != 1:
        raise ValueError(
            "Cannot uniquely identify "
            "the dark chart HTML."
        )

    return found[0]


def clone_chart(original, criteria=False):
    chart = copy.deepcopy(original)

    chart.name = (
        "_mpx_criteria_chart"
        if criteria
        else "_mpx_chart"
    )

    node = html_node(chart)
    html = node.value

    html, count = re.subn(
        r"(\b(?:let|const|var)\s+pageSize\s*=\s*)"
        r"\d+"
        r"(\s*;)",
        lambda match: (
            match[1] + "50" + match[2]
        ),
        html,
    )

    if count != 1:
        raise ValueError(
            "Cannot identify the chart's "
            "default page size."
        )

    select = re.compile(
        r"""(<select\b[^>]*\bid\s*=\s*["']pageSize["'][^>]*>)"""
        r"(.*?)"
        r"(</select\s*>)",
        re.I | re.S,
    )

    options = list(
        select.finditer(html)
    )

    if (
        len(options) != 1
        or len(
            re.findall(
                r"<option\b[^>]*>\s*50\s*</option\s*>",
                options[0][2],
                re.I,
            )
        ) != 1
    ):
        raise ValueError(
            "Cannot identify the 50-bar view option."
        )

    def selected(match):
        def option(item):
            attributes = re.sub(
                r"""\s+selected(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?""",
                "",
                item[1],
                flags=re.I,
            )

            return (
                "<option"
                + attributes
                + (
                    " selected"
                    if item[2].strip() == "50"
                    else ""
                )
                + ">"
                + item[2]
                + "</option>"
            )

        return (
            match[1]
            + re.sub(
                r"<option\b([^>]*)>(.*?)</option\s*>",
                option,
                match[2],
                flags=re.I | re.S,
            )
            + match[3]
        )

    html = select.sub(
        selected,
        html,
    )

    methodology_marker = (
        "Uses your saved checklist prizes and race dates,"
    )

    if html.count(methodology_marker) != 1:
        raise ValueError(
            "Cannot identify the existing "
            "methodology tooltip."
        )

    if criteria:
        note = (
            "Each checked criterion receives the full "
            "saved checklist prize once. "
            "Criteria overlap: attributed prizes and "
            "criterion matches can count the same "
            "checklist more than once. "
            "Shares use the sum of selected criterion "
            "totals, not unique race prizes. "
            "Invalid-date matches cannot be assigned "
            "to a period. "
        )

        replacements = {
            "Recorded prize":
                "Attributed prize",
            "Valid-prize checklists":
                "Criterion matches",
            "Participant total":
                "Criterion total",
            "Share of participant total":
                "Share of criterion total",
            "Share of comparison total":
                "Share of attributed total",
            "About the recorded totals":
                "About criterion attribution",
            "excluded records":
                "excluded criterion matches",
            "Recorded data":
                "Criterion attribution",
        }

        for old, new in replacements.items():
            html = html.replace(old, new)

        html = html.replace(
            'data.label.toLowerCase()+"s"',
            '"checklist criteria"',
        )

    else:
        note = (
            "Groups saved race prizes by the checklist "
            "stallion or breeding farm. "
            "These are horse race prizes, not fees or "
            "payments to a stallion or breeding farm. "
            "Invalid-date records cannot be assigned "
            "to a period. "
        )

    node.value = html.replace(
        methodology_marker,
        note + methodology_marker,
        1,
    )

    ast.fix_missing_locations(chart)

    return chart


def patch(source):
    tree = ast.parse(source)

    if MARKER in source:
        for name in (
            "_mpx_page",
            "_mpx_fetch",
            "_mpx_prepare",
            "_mpx_chart",
            "_mpx_criteria_chart",
        ):
            function(tree, name)

        return source, False

    if "# PRIZE_ANALYTICS_DARK_DESIGN_V1" not in source:
        raise ValueError(
            "Install "
            "implement-design-for-prize-a-month-feature.py "
            "first."
        )

    for node in tree.body:
        if (
            isinstance(node, ast.FunctionDef)
            and node.name.startswith("_mpx_")
        ):
            raise ValueError(
                "Existing _mpx_ helpers found "
                "without the installation marker."
            )

        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id.startswith("_MPX_")
                for target in node.targets
            )
        ):
            raise ValueError(
                "Conflicting _MPX_ configuration found."
            )

    for name in (
        "get_db_connection",
        "parse_race_date",
        "_mp_dates",
    ):
        function(tree, name)

    page = function(tree, "_mc_page")
    chart = function(tree, "_mct_chart")
    main = function(tree, "main")

    periods = []

    for node in ast.walk(page):
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "period"
                for target in node.targets
            )
            and isinstance(node.value, ast.Call)
        ):
            call = node.value

            if (
                isinstance(call.func, ast.Attribute)
                and call.func.attr == "radio"
            ):
                value = (
                    call.args[1]
                    if len(call.args) > 1
                    else next(
                        (
                            keyword.value
                            for keyword in call.keywords
                            if keyword.arg == "options"
                        ),
                        None,
                    )
                )

                try:
                    periods = ast.literal_eval(value)
                except (ValueError, TypeError):
                    pass

    if (
        not isinstance(periods, (list, tuple))
        or len(periods) != 4
        or not all(
            isinstance(period, str)
            for period in periods
        )
    ):
        raise ValueError(
            "Cannot read the four existing "
            "prize date-period options."
        )

    menus = []

    for node in main.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
        ):
            call = node.value

            if ast.unparse(call.func) == "st.sidebar.radio":
                menus.append(
                    (node, call)
                )

    if len(menus) != 1:
        raise ValueError(
            "Cannot uniquely identify "
            "the existing main sidebar menu."
        )

    assignment, menu = menus[0]
    page_name = assignment.targets[0].id

    choices = (
        menu.args[1]
        if len(menu.args) > 1
        else next(
            (
                keyword.value
                for keyword in menu.keywords
                if keyword.arg == "options"
            ),
            None,
        )
    )

    if (
        not isinstance(choices, (ast.List, ast.Tuple))
        or not all(
            isinstance(value, ast.Constant)
            and isinstance(value.value, str)
            for value in choices.elts
        )
    ):
        raise ValueError(
            "Expected a literal sidebar page list."
        )

    if any(
        value.value in PAGES
        for value in choices.elts
    ):
        raise ValueError(
            "An additional prize page title already exists; "
            "refusing duplicate navigation."
        )

    choices.elts.extend(
        ast.Constant(value=title)
        for title in PAGES
    )

    routes = [
        node
        for node in main.body
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == page_name
            and len(node.test.ops) == 1
            and isinstance(node.test.ops[0], ast.Eq)
        )
    ]

    if not routes:
        raise ValueError(
            "Cannot identify the existing page dispatcher."
        )

    dispatcher = routes[0]

    if (
        main.body.index(dispatcher)
        <= main.body.index(assignment)
    ):
        raise ValueError(
            "Unexpected sidebar/dispatcher order."
        )

    route = ast.parse(
        f"if {page_name} in {PAGES!r}:\n"
        f"    _mpx_page({PAGES!r}[{page_name}])\n"
        "    return\n"
    ).body[0]

    main.body.insert(
        main.body.index(dispatcher),
        route,
    )

    edits = []

    for node in tree.body:
        if not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and ast.unparse(
                node.value.func
            ) == "st.set_page_config"
        ):
            continue

        modified = False

        for keyword in node.value.keywords:
            if keyword.arg != "layout":
                continue

            for test in ast.walk(keyword.value):
                if (
                    isinstance(test, ast.Compare)
                    and any(
                        isinstance(operator, ast.In)
                        for operator in test.ops
                    )
                ):
                    for group in test.comparators:
                        if (
                            isinstance(
                                group,
                                (ast.Tuple, ast.List),
                            )
                            and any(
                                isinstance(
                                    value,
                                    ast.Constant,
                                )
                                and value.value
                                == "Checklist Review"
                                for value in group.elts
                            )
                        ):
                            present = {
                                value.value
                                for value in group.elts
                                if isinstance(
                                    value,
                                    ast.Constant,
                                )
                            }

                            group.elts.extend(
                                ast.Constant(value=title)
                                for title in PAGES
                                if title not in present
                            )

                            modified = True

        if modified:
            ast.fix_missing_locations(node)

            edits.append(
                (
                    node.lineno - 1,
                    node.end_lineno,
                    ast.unparse(node) + "\n",
                )
            )

    helpers = ast.parse(
        RUNTIME.replace(
            "__PERIODS__",
            repr(list(periods)),
            1,
        )
    ).body

    helpers.extend(
        [
            clone_chart(chart),
            clone_chart(
                chart,
                criteria=True,
            ),
        ]
    )

    ast.fix_missing_locations(main)

    addition = (
        MARKER
        + "\n"
        + "\n\n".join(
            ast.unparse(node)
            for node in helpers
        )
        + "\n\n"
    )

    edits.append(
        (
            start_line(main),
            main.end_lineno,
            addition
            + ast.unparse(main)
            + "\n\n",
        )
    )

    index = tree.body.index(main)
    tree.body[index:index] = helpers

    lines = source.splitlines(keepends=True)
    edits.sort()

    if any(
        right[0] < left[1]
        for left, right in zip(
            edits,
            edits[1:],
        )
    ):
        raise ValueError(
            "Overlapping source edits."
        )

    for start, end, text in reversed(edits):
        lines[start:end] = [text]

    result = "".join(lines)

    compile(
        result,
        "<three-additional-prize-pages>",
        "exec",
    )

    if ast.dump(
        ast.parse(result),
        include_attributes=False,
    ) != ast.dump(
        tree,
        include_attributes=False,
    ):
        raise ValueError(
            "Source changes do not match "
            "the intended page additions."
        )

    return result, True


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Add Stallion, Breeding Farm and "
            "Checklist Criteria prize dashboards."
        )
    )

    parser.add_argument(
        "app_file",
        nargs="?",
        default="app.py",
    )

    app = Path(
        parser.parse_args().app_file
    ).resolve()

    if not app.is_file():
        raise SystemExit(
            f"Application file not found: {app}"
        )

    original = app.read_bytes()

    try:
        updated, changed = patch(
            original.decode("utf-8-sig")
        )

    except Exception as error:
        raise SystemExit(
            "Validation failed. "
            "Application was not changed.\n"
            f"{error}"
        ) from error

    if not changed:
        print(
            "The three additional prize pages "
            "are already installed."
        )
        return

    stamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S-%f"
    )

    backup = app.with_name(
        f"{app.name}."
        f"before-three-prize-pages-{stamp}.bak"
    )

    temporary = None

    try:
        if app.read_bytes() != original:
            raise RuntimeError(
                "Application source changed "
                "during validation. Retry."
            )

        shutil.copy2(app, backup)

        if backup.read_bytes() != original:
            raise RuntimeError(
                "Source backup verification failed."
            )

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=app.parent,
            prefix=f".{app.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(updated)

        shutil.copymode(app, temporary)

        if app.read_bytes() != original:
            raise RuntimeError(
                "Application source changed "
                "before replacement. Retry."
            )

        temporary.replace(app)
        temporary = None

    finally:
        if (
            temporary is not None
            and temporary.exists()
        ):
            temporary.unlink()

    print(f"Updated application: {app}")
    print(f"Source backup: {backup}")
    print(
        "Added Stallion, Breeding Farm and "
        "Checklist Criteria prize pages."
    )
    print(
        "All three reuse the dark chart design "
        "and start at 50 bars per view."
    )
    print(
        "Criteria use full-prize attribution "
        "per checked criterion; overlap is "
        "explained in tooltips."
    )
    print(
        "No database records or schema were changed."
    )
    print(
        "Original comparison functions and "
        "other page content were preserved."
    )
    print(
        "Restart Streamlit and test all three pages, "
        "including iPad tooltips."
    )


if __name__ == "__main__":
    main()