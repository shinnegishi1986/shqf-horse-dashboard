# scripts/add-month-comparison.py
#
# Adds:
#   - Monthly Jockey Prize page
#   - Monthly Horse Owner Prize page
#
# Features:
#   - Current year/month defaults using JST
#   - Select jockeys or horse owners
#   - Stacked horizontal prize bars, colored by venue
#   - Highest total prize first
#   - Totals, venue breakdown, and CSV download
#   - Account-scoped records
#   - Independent of Checklist Review filters
#
# Does not change database records or schema.
# Creates a timestamped app.py source backup.
#
# Stop Streamlit before running:
#
#   python scripts/add-month-comparison.py app.py

RUNTIME = r'''
# MONTHLY_PRIZE_COMPARISON_V1

def _mc_config(kind):
    options = {
        "jockey": (
            "jockey_id",
            "jockey_name",
            "Jockey",
            "Jockeys",
            get_user_jockeys,
        ),
        "owner": (
            "horse_owner_id",
            "horse_owner_name",
            "Horse Owner",
            "Horse Owners",
            get_user_horse_owners,
        ),
    }

    if kind not in options:
        raise ValueError("Unknown monthly comparison type.")

    return options[kind]


def _mc_bounds(year, month):
    from datetime import date

    start = date(int(year), int(month), 1)

    if start.month == 12:
        end = date(start.year + 1, 1, 1)
    else:
        end = date(start.year, start.month + 1, 1)

    return start.isoformat(), end.isoformat()


def _mc_fetch(owner_id, kind, year, month):
    column = _mc_config(kind)[0]
    start, end = _mc_bounds(year, month)

    conn = get_db_connection()

    try:
        # The entity column comes only from the fixed configuration.
        return [
            dict(row)
            for row in conn.execute(
                f"SELECT c.id,c.date_of_race,c.{column} AS entity_id,"
                "c.venue_id,v.venue_name,c.prize "
                "FROM checklists c "
                "LEFT JOIN venues v "
                "ON v.id=c.venue_id AND v.owner_id=c.owner_id "
                "WHERE c.owner_id=? "
                "AND c.date_of_race>=? "
                "AND c.date_of_race<?",
                (owner_id, start, end),
            ).fetchall()
        ]

    finally:
        conn.close()


def _mc_names(rows, column):
    from collections import Counter

    names = {
        row["id"]: str(row.get(column) or "(Unnamed)")
        for row in rows
    }

    counts = Counter(names.values())

    return {
        item_id: (
            name
            if counts[name] == 1
            else f"{name} (#{item_id})"
        )
        for item_id, name in names.items()
    }


def _mc_prepare(
    rows,
    names,
    selected,
    year,
    month,
    label,
):
    import math
    from datetime import date
    from collections import Counter, defaultdict

    selected = list(
        dict.fromkeys(
            item_id
            for item_id in selected
            if item_id in names
        )
    )

    selected_set = set(selected)
    groups = defaultdict(list)
    venues = {}

    valid_counts = Counter()
    missing_counts = Counter()
    invalid_counts = Counter()
    invalid_dates = 0

    for row in rows:
        entity_id = row["entity_id"]

        if entity_id not in selected_set:
            continue

        try:
            race_date = date.fromisoformat(
                str(row["date_of_race"])[:10]
            )
        except (ValueError, TypeError):
            invalid_dates += 1
            continue

        if (
            race_date.year,
            race_date.month,
        ) != (
            int(year),
            int(month),
        ):
            continue

        raw = row.get("prize")

        if (
            raw is None
            or (
                isinstance(raw, str)
                and not raw.strip()
            )
        ):
            missing_counts[entity_id] += 1
            continue

        try:
            prize = float(raw)

            if not math.isfinite(prize) or prize < 0:
                raise ValueError()

        except (ValueError, TypeError, OverflowError):
            invalid_counts[entity_id] += 1
            continue

        venue_id = row.get("venue_id")

        venues[venue_id] = str(
            row.get("venue_name")
            or (
                "(No venue recorded)"
                if venue_id is None
                else "(Unavailable venue)"
            )
        )

        groups[(entity_id, venue_id)].append(prize)
        valid_counts[entity_id] += 1

    duplicates = Counter(venues.values())

    venue_names = {
        venue_id: (
            name
            if duplicates[name] == 1
            else f"{name} (#{venue_id})"
        )
        for venue_id, name in venues.items()
    }

    venue_order = sorted(
        venues,
        key=lambda value: (
            venue_names[value].casefold(),
            str(value),
        ),
    )

    try:
        sums = {
            key: math.fsum(values)
            for key, values in groups.items()
        }

        totals = {
            entity_id: math.fsum(
                sums.get((entity_id, venue), 0.0)
                for venue in venue_order
            )
            for entity_id in selected
        }

        total = math.fsum(totals.values())

    except OverflowError:
        raise ValueError(
            "Prize totals overflowed. "
            "Check the recorded prize values."
        )

    if not all(
        math.isfinite(value)
        for value in (
            list(sums.values())
            + list(totals.values())
            + [total]
        )
    ):
        raise ValueError(
            "A prize total is not finite. "
            "Check the recorded prize values."
        )

    ordered = sorted(
        selected,
        key=lambda value: (
            -totals[value],
            names[value].casefold(),
            value,
        ),
    )

    chart_rows = []
    table_rows = []

    for entity_id in ordered:
        record = {
            label + " ID": entity_id,
            label: names[entity_id],
            "Total Prize (JPY)": totals[entity_id],
            "Checklists with valid prize": valid_counts[entity_id],
            "Missing prize": missing_counts[entity_id],
            "Invalid prize": invalid_counts[entity_id],
        }

        for rank, venue in enumerate(venue_order):
            prize = sums.get(
                (entity_id, venue),
                0.0,
            )

            record[
                "Venue: " + venue_names[venue]
            ] = prize

            chart_rows.append({
                "entity": names[entity_id],
                "venue": venue_names[venue],
                "prize": prize,
                "entity_total": totals[entity_id],
                "checklists": len(
                    groups.get(
                        (entity_id, venue),
                        [],
                    )
                ),
                "venue_order": rank,
            })

        table_rows.append(record)

    return chart_rows, table_rows, {
        "total": total,
        "valid": sum(valid_counts.values()),
        "missing": sum(missing_counts.values()),
        "invalid": sum(invalid_counts.values()),
        "invalid_dates": invalid_dates,
        "venues": len(venues),
        "entity_order": [
            names[item_id]
            for item_id in ordered
        ],
        "venue_order": [
            venue_names[venue]
            for venue in venue_order
        ],
    }


def _mc_set_selected(key, values):
    st.session_state[key] = list(values)


def _mc_page(kind):
    import calendar
    import pandas as pd
    from datetime import datetime, timedelta, timezone

    owner_id = st.session_state.user_id

    column, name_column, label, plural, getter = _mc_config(kind)

    today = datetime.now(
        timezone(timedelta(hours=9))
    ).date()

    prefix = f"mc_{kind}_{owner_id}"

    st.header(f"Monthly Prize by {label}")

    st.caption(
        "Defaults use the current year and month in "
        "Japan Standard Time (JST). Bars compare recorded "
        "checklist prize totals, with each color "
        "representing a venue."
    )

    first, second = st.columns(2)

    with first:
        year = int(
            st.number_input(
                "Year",
                min_value=1980,
                max_value=2100,
                value=today.year,
                step=1,
                key=prefix + "_year",
            )
        )

    with second:
        month = st.selectbox(
            "Month",
            list(range(1, 13)),
            index=today.month - 1,
            format_func=lambda value: (
                f"{value:02d} — {calendar.month_name[value]}"
            ),
            key=prefix + "_month",
        )

    names = _mc_names(
        getter(owner_id),
        name_column,
    )

    if not names:
        st.info(
            f"Register {plural.lower()} or save "
            "checklist references first."
        )
        return

    rows = _mc_fetch(
        owner_id,
        kind,
        year,
        month,
    )

    options = sorted(
        names,
        key=lambda value: (
            names[value].casefold(),
            value,
        ),
    )

    present = {
        row["entity_id"]
        for row in rows
    }

    initial = [
        item_id
        for item_id in options
        if item_id in present
    ]

    selection_key = (
        f"{prefix}_selected_{year}_{month:02d}"
    )

    if selection_key in st.session_state:
        st.session_state[selection_key] = [
            item_id
            for item_id in st.session_state[selection_key]
            if item_id in names
        ]

    all_column, clear_column = st.columns(2)

    with all_column:
        st.button(
            "Select all registered " + plural.lower(),
            key=prefix + "_all",
            on_click=_mc_set_selected,
            args=(selection_key, options),
        )

    with clear_column:
        st.button(
            "Clear selection",
            key=prefix + "_clear",
            on_click=_mc_set_selected,
            args=(selection_key, []),
        )

    selected = st.multiselect(
        "Compare " + plural.lower(),
        options,
        default=(
            None
            if selection_key in st.session_state
            else initial
        ),
        format_func=lambda value: names[value],
        key=selection_key,
        help=(
            "Defaults to registered participants appearing "
            "in this month's checklist records. Select all "
            "registered to include names with no records. "
            "An empty selection shows no comparison."
        ),
    )

    st.caption(
        "Uses race date, not entry date, and all finishing "
        "places. Checklist Review filters do not apply. "
        "Only your account's records are included. Missing, "
        "invalid, non-finite, and negative prizes are excluded; "
        "a recorded zero is included. These are recorded "
        "prizes, not calculated jockey fees or owner payout shares."
    )

    if not selected:
        st.info(
            f"Select one or more {plural.lower()} to compare."
        )
        return

    try:
        chart_rows, table_rows, stats = _mc_prepare(
            rows,
            names,
            selected,
            year,
            month,
            label,
        )

    except ValueError as error:
        st.error(str(error))
        return

    a, b, c, d = st.columns(4)

    a.metric(
        "Total Recorded Prize",
        f"JPY {stats['total']:,.0f}",
    )

    b.metric(
        "Checklists with Valid Prize",
        f"{stats['valid']:,}",
    )

    c.metric(
        "Selected " + plural,
        f"{len(selected):,}",
    )

    d.metric(
        "Venues with Valid Prize",
        f"{stats['venues']:,}",
    )

    st.caption(
        "Excluded within the selection: "
        f"{stats['missing']:,} missing prize, "
        f"{stats['invalid']:,} invalid prize, "
        f"{stats['invalid_dates']:,} invalid race date."
    )

    if len(selected) > 50:
        st.warning(
            "Many names are selected. Narrow the selection "
            "for a more readable chart."
        )

    if chart_rows and stats["total"] > 0:
        spec = {
            "height": max(
                320,
                min(3600, 34 * len(selected)),
            ),
            "mark": {
                "type": "bar",
            },
            "encoding": {
                "y": {
                    "field": "entity",
                    "type": "nominal",
                    "title": label,
                    "sort": stats["entity_order"],
                    "axis": {
                        "labelLimit": 260,
                    },
                },
                "x": {
                    "field": "prize",
                    "type": "quantitative",
                    "stack": "zero",
                    "title": "Recorded Prize (JPY)",
                    "axis": {
                        "format": ",.0f",
                    },
                },
                "color": {
                    "field": "venue",
                    "type": "nominal",
                    "title": "Venue",
                    "scale": {
                        "domain": stats["venue_order"],
                        "scheme": "tableau20",
                    },
                    "legend": {
                        "orient": "bottom",
                        "columns": 3,
                        "labelLimit": 250,
                    },
                },
                "order": {
                    "field": "venue_order",
                    "type": "quantitative",
                    "sort": "ascending",
                },
                "tooltip": [
                    {
                        "field": "entity",
                        "type": "nominal",
                        "title": label,
                    },
                    {
                        "field": "venue",
                        "type": "nominal",
                        "title": "Venue",
                    },
                    {
                        "field": "prize",
                        "type": "quantitative",
                        "title": "Venue Prize (JPY)",
                        "format": ",.0f",
                    },
                    {
                        "field": "entity_total",
                        "type": "quantitative",
                        "title": "Total Prize (JPY)",
                        "format": ",.0f",
                    },
                    {
                        "field": "checklists",
                        "type": "quantitative",
                        "title": "Checklists",
                        "format": ",.0f",
                    },
                ],
            },
        }

        st.vega_lite_chart(
            pd.DataFrame(chart_rows),
            spec=spec,
            width="stretch",
        )

    else:
        st.info(
            "No positive recorded prize is available "
            "for this selection. Zero totals are shown below."
        )

    st.subheader(
        f"{year}-{month:02d} — Prize Totals and Venue Breakdown"
    )

    table = pd.DataFrame(table_rows)

    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
    )

    st.download_button(
        "Download Monthly Comparison CSV",
        table.to_csv(index=False).encode("utf-8-sig"),
        file_name=(
            f"monthly_{kind}_prize_{year}_{month:02d}.csv"
        ),
        mime="text/csv",
        key=prefix + "_download",
    )

    st.caption(
        "Each checklist contributes its recorded prize once "
        "to the selected comparison. Totals reflect only "
        "records saved in this app; they are not a complete "
        "racing earnings ledger. Records without an available "
        "registered jockey/horse owner are not selectable."
    )

'''

import argparse
import ast
import copy
from datetime import datetime
from pathlib import Path
import shutil
import tempfile


MARKER = "# MONTHLY_PRIZE_COMPARISON_V1"

PAGES = [
    ("Monthly Jockey Prize", "jockey"),
    ("Monthly Horse Owner Prize", "owner"),
]


def find_function(tree, name):
    nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == name
    ]

    if len(nodes) != 1:
        raise ValueError(
            f"Expected one {name}; found {len(nodes)}."
        )

    return nodes[0]


def assignment_names(node):
    if not isinstance(node, ast.Assign):
        return set()

    return {
        item.id
        for target in node.targets
        for item in ast.walk(target)
        if isinstance(item, ast.Name)
    }


def definition_start(node):
    return min(
        [node.lineno]
        + [
            decorator.lineno
            for decorator in node.decorator_list
        ]
    ) - 1


def patch_application(source):
    if MARKER in source:
        return source, False

    tree = ast.parse(source)
    main_function = find_function(tree, "main")

    for name in (
        "get_db_connection",
        "get_user_jockeys",
        "get_user_horse_owners",
    ):
        find_function(tree, name)

    helpers = {
        node.name
        for node in ast.parse(RUNTIME).body
        if isinstance(node, ast.FunctionDef)
    }

    existing = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }

    if helpers & existing:
        raise ValueError(
            "Conflicting monthly comparison helper names "
            "already exist."
        )

    main_start = definition_start(main_function)
    main_end = main_function.end_lineno

    navigation = [
        (index, node.value)
        for index, node in enumerate(main_function.body)
        if (
            isinstance(node, ast.Assign)
            and "page" in assignment_names(node)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "radio"
        )
    ]

    if len(navigation) != 1:
        raise ValueError(
            "Cannot uniquely identify the main page navigation."
        )

    navigation_index, call = navigation[0]

    options = (
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

    if not isinstance(options, (ast.List, ast.Tuple)):
        raise ValueError(
            "Expected a literal navigation options list."
        )

    labels = [
        node.value
        if isinstance(node, ast.Constant)
        else None
        for node in options.elts
    ]

    if any(
        label in labels
        for label, kind in PAGES
    ):
        raise ValueError(
            "A monthly comparison page already exists "
            "without this patch marker."
        )

    position = (
        labels.index("Checklist Review") + 1
        if "Checklist Review" in labels
        else len(labels)
    )

    options.elts[position:position] = [
        ast.Constant(label)
        for label, kind in PAGES
    ]

    logout = [
        index
        for index, node in enumerate(main_function.body)
        if (
            index > navigation_index
            and isinstance(node, ast.If)
            and any(
                isinstance(value, ast.Constant)
                and value.value == "Logout"
                for value in ast.walk(node.test)
            )
        )
    ]

    if len(logout) != 1:
        raise ValueError(
            "Cannot identify the logout handler; "
            "routing was not changed."
        )

    branches = []

    for label, kind in PAGES:
        branches += ast.parse(
            f"if page == {label!r}:\n"
            f"    _mc_page({kind!r})\n"
            "    return\n"
        ).body

    main_function.body[
        logout[0] + 1:logout[0] + 1
    ] = branches

    ast.fix_missing_locations(main_function)

    edits = [
        (
            main_start,
            main_end,
            ast.unparse(main_function) + "\n\n",
        )
    ]

    configs = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and isinstance(node.value.func.value, ast.Name)
            and node.value.func.value.id == "st"
            and node.value.func.attr == "set_page_config"
        )
    ]

    if len(configs) != 1:
        raise ValueError(
            "Expected one top-level Streamlit page configuration."
        )

    config = configs[0]

    layout = next(
        (
            keyword
            for keyword in config.value.keywords
            if keyword.arg == "layout"
        ),
        None,
    )

    config_changed = False

    if layout is None:
        layout = ast.keyword(
            arg="layout",
            value=ast.Constant("centered"),
        )
        config.value.keywords.append(layout)

    if not (
        isinstance(layout.value, ast.Constant)
        and layout.value.value == "wide"
    ):
        previous = copy.deepcopy(layout.value)

        test = ast.parse(
            "st.session_state.get('logged_in', False) and "
            "st.session_state.get('app_navigation_page') in "
            + repr([
                label
                for label, kind in PAGES
            ]),
            mode="eval",
        ).body

        layout.value = ast.IfExp(
            test=test,
            body=ast.Constant("wide"),
            orelse=previous,
        )

        ast.fix_missing_locations(config)

        edits.append(
            (
                config.lineno - 1,
                config.end_lineno,
                ast.unparse(config) + "\n",
            )
        )

        config_changed = True

    edits.sort()

    if any(
        right[0] < left[1]
        for left, right in zip(edits, edits[1:])
    ):
        raise ValueError("Overlapping source edits.")

    lines = source.splitlines(keepends=True)

    for start, end, text in reversed(edits):
        lines[start:end] = [text]

    intermediate = "".join(lines)

    first = next(
        node
        for node in ast.parse(intermediate).body
        if isinstance(
            node,
            (ast.FunctionDef, ast.ClassDef),
        )
    )

    lines = intermediate.splitlines(keepends=True)

    lines.insert(
        definition_start(first),
        RUNTIME.strip("\n") + "\n\n",
    )

    updated = "".join(lines)

    compile(
        updated,
        "<monthly-prize-comparison>",
        "exec",
    )

    def normalize(text):
        parsed = ast.parse(text)
        kept = []

        for node in parsed.body:
            if (
                isinstance(node, ast.FunctionDef)
                and node.name in helpers | {"main"}
            ):
                continue

            if (
                config_changed
                and isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and isinstance(node.value.func.value, ast.Name)
                and node.value.func.value.id == "st"
                and node.value.func.attr == "set_page_config"
            ):
                continue

            kept.append(node)

        return ast.dump(
            ast.Module(
                body=kept,
                type_ignores=[],
            ),
            include_attributes=False,
        )

    if normalize(source) != normalize(updated):
        raise ValueError(
            "Unexpected changes outside monthly comparison "
            "and navigation integration."
        )

    if updated.count(MARKER) != 1:
        raise ValueError(
            "Invalid monthly comparison patch marker."
        )

    return updated, True


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Add monthly jockey and horse-owner "
            "prize comparison pages."
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
        updated, changed = patch_application(
            original.decode("utf-8-sig")
        )

    except Exception as error:
        raise SystemExit(
            "Validation failed. Application was not changed.\n"
            f"{error}"
        ) from error

    if not changed:
        print(
            "Monthly prize comparison pages "
            "are already installed."
        )
        return

    stamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S-%f"
    )

    backup = app.with_name(
        f"{app.name}."
        f"before-month-comparison-{stamp}.bak"
    )

    temporary = None

    try:
        if app.read_bytes() != original:
            raise RuntimeError(
                "Application source changed during validation. "
                "Retry the patch."
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
                "Application source changed before replacement. "
                "Retry the patch."
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
    print("Syntax and AST change-scope validation passed.")
    print(
        "Added Monthly Jockey Prize "
        "and Monthly Horse Owner Prize pages."
    )
    print(
        "Defaults use the current year and month in JST."
    )
    print(
        "Select names to compare total recorded prize, "
        "stacked by venue."
    )
    print(
        "No database schema or records "
        "were changed by this script."
    )
    print(
        "Existing checklist, template, blog, "
        "and filter logic was preserved."
    )
    print(
        "Restart Streamlit. "
        "Interactive browser testing remains required."
    )


if __name__ == "__main__":
    main()