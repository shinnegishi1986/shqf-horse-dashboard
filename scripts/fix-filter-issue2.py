# scripts/fix-filter-issue.py
#
# Fixes collapsed numeric filter values after updating a checklist.
#
# Reported pattern:
#   distance_to           -> 0
#   previous_distance_to  -> 0
#   interval_days_to      -> 0
#   weight_change_to      -> -999.9
#   odds_to               -> 0.0
#   prize_to              -> 0.0
#   bracket_to            -> 1
#   horse_to              -> 1
#   weight_to             -> 0.0
#
# Changes:
#   1. Repairs this specific multi-field collapsed-range pattern before
#      the review widgets are created.
#   2. Preserves numeric filter values in a separate, non-widget session
#      dictionary.
#   3. Uses those values, or get_filter_defaults(), when a numeric widget's
#      Session State key no longer exists.
#   4. Avoids supplying a competing numeric widget default when its value
#      is already present in Session State.
#
# Ordinary single-field zero ranges are NOT automatically reset.
# Repair requires at least seven collapsed upper bounds and all detected
# optional numeric filter switches to be disabled.
#
# Does NOT:
#   - Change database records or stored horse weights.
#   - Delete saved filters.
#   - Reset all filter conditions.
#   - Change filter_checklists() or bypass intentional filters.
#   - Change charts, table styling, or pagination.
#
# Run:
#   python scripts/fix-filter-issue.py
#
# Or:
#   python scripts/fix-filter-issue.py app.py
#
# A backup is created before changes are written.

import argparse
import ast
from pathlib import Path
import shutil
import tempfile


MARKER = "# REVIEW_STABLE_NUMERIC_FILTER_VALUES_V1"
NUMBER_HELPER = "_review_stable_numeric_filter_input"


HELPERS = r'''
# REVIEW_STABLE_NUMERIC_FILTER_VALUES_V1
def _review_numeric_filter_cache(owner_id):
    key = f"review_numeric_filter_cache_v1_{owner_id}"

    cache = st.session_state.get(key)

    if not isinstance(cache, dict):
        cache = {}
        st.session_state[key] = cache

    return cache


def _review_numeric_filter_identity(owner_id, widget_key):
    if not isinstance(widget_key, str):
        return None

    for prefix in (
        f"saved_filter_{owner_id}_",
        f"second_filter_{owner_id}_",
    ):
        if widget_key.startswith(prefix):
            return prefix, widget_key[len(prefix):]

    return None


def _review_repair_collapsed_numeric_filters(owner_id):
    defaults = get_filter_defaults()
    cache = _review_numeric_filter_cache(owner_id)

    collapsed_minimums = {
        "distance_to": 0,
        "previous_distance_to": 0,
        "interval_days_to": 0,
        "weight_change_to": -999.9,
        "odds_to": 0.0,
        "prize_to": 0.0,
        "bracket_to": 1,
        "horse_to": 1,
        "weight_to": 0.0,
    }

    optional_switches = (
        "enable_distance_filter",
        "enable_previous_distance_filter",
        "enable_interval_days_filter",
        "enable_weight_change_filter",
        "enable_bracket_filter",
        "enable_horse_filter",
        "enable_weight_filter",
    )

    repaired = []

    for prefix, title in (
        (f"saved_filter_{owner_id}_", "First Filter"),
        (f"second_filter_{owner_id}_", "Second Filter"),
    ):
        # Do not reinterpret a set of enabled optional numeric filters.
        if any(
            bool(st.session_state.get(prefix + field, False))
            for field in optional_switches
        ):
            continue

        collapsed = [
            field
            for field, minimum in collapsed_minimums.items()
            if (
                field in defaults
                and prefix + field in st.session_state
                and st.session_state[prefix + field] == minimum
                and defaults[field] != minimum
            )
        ]

        # This targets the multi-field failure in the supplied diagnostic,
        # rather than treating any legitimate zero upper bound as a bug.
        if len(collapsed) < 7:
            continue

        for field in collapsed:
            key = prefix + field
            value = defaults[field]

            st.session_state[key] = value
            cache[key] = value

        repaired.append(
            title + ": " + ", ".join(collapsed)
        )

    if repaired:
        st.session_state[
            f"review_numeric_filter_repair_notice_{owner_id}"
        ] = repaired


def _review_show_numeric_filter_repair_notice(owner_id):
    repaired = st.session_state.pop(
        f"review_numeric_filter_repair_notice_{owner_id}",
        [],
    )

    if repaired:
        st.info(
            "Recovered numeric filter upper bounds that had all fallen "
            "back to their minimum values. Other filter choices were "
            "preserved. Check Current Review Filters to confirm the ranges."
        )

        for message in repaired:
            st.caption(message)


def _review_stable_numeric_filter_input(
    widget_function,
    owner_id,
    *args,
    **kwargs,
):
    widget_key = kwargs.get("key")
    identity = _review_numeric_filter_identity(owner_id, widget_key)

    if identity is None:
        return widget_function(*args, **kwargs)

    _, field = identity
    defaults = get_filter_defaults()

    if field not in defaults:
        return widget_function(*args, **kwargs)

    default = defaults[field]

    # Leave nonnumeric fields and boolean switches to their own widgets.
    if isinstance(default, bool) or not isinstance(default, (int, float)):
        return widget_function(*args, **kwargs)

    cache = _review_numeric_filter_cache(owner_id)

    if widget_key not in st.session_state:
        # Recover a previously rendered value when a conditional widget's
        # own key has disappeared. Otherwise use the app's real default,
        # not the number input's minimum.
        value = cache.get(widget_key, default)

        if value is None:
            value = default

        st.session_state[widget_key] = value

    # Session State is the single source of the initial widget value.
    # Existing number inputs in this app use keyword arguments for value.
    kwargs["value"] = None

    result = widget_function(*args, **kwargs)

    # A filter number input is not intended to remain blank.
    # Keep a usable fallback in the independent cache without mutating
    # the widget's Session State after it has been instantiated.
    if result is not None:
        cache[widget_key] = result
        return result

    fallback = cache.get(widget_key, default)

    if fallback is None:
        fallback = default

    cache[widget_key] = fallback
    return fallback

'''


def find_function(tree, name):
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == name
    ]

    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one {name} function; found {len(matches)}."
        )

    return matches[0]


def is_review_header(statement):
    if not (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
    ):
        return False

    call = statement.value

    return (
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "st"
        and call.func.attr in {"header", "title", "subheader"}
        and bool(call.args)
        and isinstance(call.args[0], ast.Constant)
        and call.args[0].value == "Checklist Review"
    )


def numeric_filter_key(call):
    if not (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "st"
        and call.func.attr == "number_input"
    ):
        return None

    key = next(
        (
            keyword.value
            for keyword in call.keywords
            if keyword.arg == "key"
        ),
        None,
    )

    if not (
        isinstance(key, ast.Call)
        and isinstance(key.func, ast.Name)
        and key.func.id in {
            "saved_filter_key",
            "second_filter_key",
        }
        and len(key.args) == 2
        and isinstance(key.args[0], ast.Name)
        and key.args[0].id == "owner_id"
        and isinstance(key.args[1], ast.Constant)
        and isinstance(key.args[1].value, str)
    ):
        return None

    return key.args[1].value


class StabilizeFilterNumberInputs(ast.NodeTransformer):
    def __init__(self):
        self.fields = set()
        self.count = 0

    def visit_FunctionDef(self, node):
        # Do not alter nested callback implementations.
        return node

    def visit_AsyncFunctionDef(self, node):
        return node

    def visit_Call(self, node):
        field = numeric_filter_key(node)

        if field is None:
            return self.generic_visit(node)

        # More than the label as a positional argument would require
        # translating positional min/max/value arguments.
        if len(node.args) > 1:
            raise ValueError(
                "A filter number input uses unexpected positional "
                f"arguments at line {node.lineno}."
            )

        self.fields.add(field)
        self.count += 1

        return ast.copy_location(
            ast.Call(
                func=ast.Name(
                    id=NUMBER_HELPER,
                    ctx=ast.Load(),
                ),
                args=[
                    node.func,
                    ast.Name(id="owner_id", ctx=ast.Load()),
                    *node.args,
                ],
                keywords=node.keywords,
            ),
            node,
        )


def validate_scope(original, updated, changed_names):
    helper_names = {
        node.name
        for node in ast.parse(HELPERS).body
        if isinstance(node, ast.FunctionDef)
    }

    allowed = set(changed_names) | helper_names

    def normalize(source):
        tree = ast.parse(source)

        tree.body = [
            node
            for node in tree.body
            if not (
                isinstance(node, ast.FunctionDef)
                and node.name in allowed
            )
        ]

        return ast.dump(tree, include_attributes=False)

    if normalize(original) != normalize(updated):
        raise ValueError(
            "Unexpected changes outside numeric filter rendering "
            "and the repair helpers."
        )

    if updated.count(MARKER) != 1:
        raise ValueError("Invalid numeric-filter patch marker.")


def patch_application(source):
    if MARKER in source:
        return source, 0

    tree = ast.parse(source)
    find_function(tree, "get_filter_defaults")

    review = find_function(
        tree,
        "render_checklist_review_page",
    )

    helper_names = {
        node.name
        for node in ast.parse(HELPERS).body
        if isinstance(node, ast.FunctionDef)
    }

    if any(
        isinstance(node, ast.FunctionDef)
        and node.name in helper_names
        for node in tree.body
    ):
        raise ValueError(
            "A proposed repair helper already exists without "
            "the expected patch marker."
        )

    # Include any top-level UI function with matching filter number inputs.
    # This normally includes the review page and second-filter section.
    candidates = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.FunctionDef)
            and any(
                isinstance(item, ast.Call)
                and numeric_filter_key(item) is not None
                for item in ast.walk(node)
            )
        )
    ]

    if review not in candidates:
        raise ValueError(
            "No supported numeric filter inputs were found in the review page."
        )

    original_spans = {}

    for function in candidates:
        argument_names = {
            argument.arg
            for argument in (
                function.args.posonlyargs
                + function.args.args
                + function.args.kwonlyargs
            )
        }

        assigns_owner = any(
            isinstance(statement, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "owner_id"
                for target in statement.targets
            )
            for statement in function.body
        )

        if "owner_id" not in argument_names and not assigns_owner:
            raise ValueError(
                f"Cannot safely resolve owner_id inside {function.name}."
            )

        start = min(
            [function.lineno]
            + [
                decorator.lineno
                for decorator in function.decorator_list
            ]
        ) - 1

        original_spans[function.name] = (
            start,
            function.end_lineno,
        )

    header_positions = [
        index
        for index, statement in enumerate(review.body)
        if is_review_header(statement)
    ]

    if len(header_positions) != 1:
        raise ValueError(
            "Could not uniquely identify the Checklist Review header."
        )

    header_position = header_positions[0]

    # Run after the existing initialization/restoration code, but before
    # the page creates its filter widgets.
    review.body.insert(
        header_position,
        ast.parse(
            "_review_repair_collapsed_numeric_filters(owner_id)"
        ).body[0],
    )

    # Keep the repair notice after the header and any immediately placed
    # Current Review Filters diagnostic container.
    notice_position = header_position + 2

    if notice_position < len(review.body):
        next_statement = review.body[notice_position]

        if (
            isinstance(next_statement, ast.Expr)
            and isinstance(next_statement.value, ast.Call)
            and isinstance(next_statement.value.func, ast.Name)
            and next_statement.value.func.id
            == "_current_review_filter_place_panel"
        ):
            notice_position += 1

    review.body.insert(
        notice_position,
        ast.parse(
            "_review_show_numeric_filter_repair_notice(owner_id)"
        ).body[0],
    )

    edits = []
    changed_names = []
    total_count = 0

    for function in candidates:
        transformer = StabilizeFilterNumberInputs()

        function.body = [
            transformer.visit(statement)
            for statement in function.body
        ]

        if not transformer.count:
            continue

        if function is review and not {
            "odds_from",
            "odds_to",
            "prize_from",
            "prize_to",
        }.issubset(transformer.fields):
            raise ValueError(
                "Could not identify all first-filter odds/prize inputs."
            )

        total_count += transformer.count
        changed_names.append(function.name)

        ast.fix_missing_locations(function)

        start, end = original_spans[function.name]

        edits.append(
            (
                start,
                end,
                ast.unparse(function) + "\n\n",
            )
        )

    ordered = sorted(edits, key=lambda item: item[0])

    for previous, current in zip(ordered, ordered[1:]):
        if current[0] < previous[1]:
            raise ValueError("Overlapping UI function replacements detected.")

    lines = source.splitlines(keepends=True)

    for start, end, replacement in reversed(ordered):
        lines[start:end] = [replacement]

    lines.insert(
        ordered[0][0],
        HELPERS.strip("\n") + "\n\n",
    )

    updated = "".join(lines)

    compile(updated, "<stable-review-numeric-filters>", "exec")
    validate_scope(source, updated, changed_names)

    return updated, total_count


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Repair collapsed Checklist Review numeric ranges "
            "and preserve numeric filter values across widget recreation."
        )
    )

    parser.add_argument(
        "app_file",
        nargs="?",
        default="app.py",
        help="Application file to update. Default: app.py",
    )

    app_path = Path(parser.parse_args().app_file).resolve()

    if not app_path.is_file():
        raise SystemExit(f"Application file not found: {app_path}")

    source = app_path.read_text(encoding="utf-8-sig")

    if MARKER in source:
        print(f"The stable numeric-filter fix is installed: {app_path}")
        return

    try:
        updated, count = patch_application(source)
    except Exception as error:
        raise SystemExit(
            "Validation failed. Application was not changed.\n"
            f"{error}"
        ) from error

    backup_path = app_path.with_name(
        f"{app_path.name}.before-stable-numeric-filter-fix.bak"
    )

    if backup_path.exists():
        raise SystemExit(
            f"Backup already exists: {backup_path}\n"
            "Move or rename it before applying this patch."
        )

    shutil.copy2(app_path, backup_path)
    temporary_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=app_path.parent,
            prefix=f".{app_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(updated)

        shutil.copymode(app_path, temporary_path)
        temporary_path.replace(app_path)

    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()

    print(f"Updated application: {app_path}")
    print(f"Backup: {backup_path}")
    print("Python syntax and patch-scope validation passed.")
    print(f"Stabilized numeric filter widget calls: {count}")
    print("Added recovery for the reported multi-field collapsed-range pattern.")
    print("No database records or saved filters were changed.")
    print("Restart or redeploy the app, then reload Checklist Review.")
    print("Check Current Review Filters:")
    print("  odds_to should use its intended value, normally 999.9.")
    print("  prize_to should use its intended value, normally 1000000000.0.")
    print("Then update a horse and confirm the ranges remain unchanged.")
    print("Interactive Streamlit testing is still required.")


if __name__ == "__main__":
    main()