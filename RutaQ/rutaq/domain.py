"""Validated departure offers and exact classical feasibility baselines."""
from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class TransferOption:
    option_id: str
    travel_time_minutes: int
    available_seats: int | None
    wheelchair_accessible: bool


@dataclass(frozen=True)
class SelectionConstraints:
    max_travel_time_minutes: int
    min_available_seats: int | None
    requires_wheelchair_access: bool


def validate_problem(options, constraints):
    """Bound the encoding to 2, 4, 8 or 16 offers and small integer fields."""
    if len(options) not in (2, 4, 8, 16):
        raise ValueError("Use 2, 4, 8 or 16 options; padding is not implicit.")
    ids = [o.option_id for o in options]
    if any(not isinstance(i, str) or not i.strip() for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("Option IDs must be nonempty and unique.")
    if type(constraints.max_travel_time_minutes) is not int or not 0 <= constraints.max_travel_time_minutes <= 63:
        raise ValueError("Time limit must be an integer from 0 to 63 minutes.")
    minimum = constraints.min_available_seats
    if minimum is not None and (type(minimum) is not int or not 0 <= minimum <= 7):
        raise ValueError("Seat limit must be None or an integer from 0 to 7.")
    if type(constraints.requires_wheelchair_access) is not bool:
        raise ValueError("Wheelchair requirement must be a boolean.")
    for option in options:
        if type(option.travel_time_minutes) is not int or not 0 <= option.travel_time_minutes <= 63:
            raise ValueError("Option time must be an integer from 0 to 63 minutes.")
        seats = option.available_seats
        if seats is not None and (type(seats) is not int or not 0 <= seats <= 7):
            raise ValueError("Available seats must be None or an integer from 0 to 7.")
        if minimum is not None and seats is None:
            raise ValueError("Cannot evaluate seating when availability is unknown.")
        if type(option.wheelchair_accessible) is not bool:
            raise ValueError("Wheelchair confirmation must be a boolean.")


def is_option_feasible(option, constraints):
    """Evaluate the same predicate used by the reversible quantum oracle."""
    return (option.travel_time_minutes <= constraints.max_travel_time_minutes
            and (constraints.min_available_seats is None or
                 (option.available_seats is not None and option.available_seats >= constraints.min_available_seats))
            and (not constraints.requires_wheelchair_access or option.wheelchair_accessible))


def classical_baseline(options, constraints):
    """Return exact solutions and scan costs; never treat random sampling as a solver."""
    validate_problem(options, constraints)
    indices = [i for i, option in enumerate(options) if is_option_feasible(option, constraints)]
    return {"feasible_indices": indices, "full_scan_predicate_evaluations": len(options),
            "first_match_predicate_evaluations": indices[0]+1 if indices else len(options),
            "finds_feasible_option": bool(indices),
            "expected_first_match_checks_random_order": (len(options)+1)/(len(indices)+1) if indices else len(options)}


def load_problem(path):
    """Read a snapshot without contacting any network service at runtime."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return parse_problem(data)


def parse_problem(data):
    """Validate a decoded scenario while allowing callers to retain its provenance."""
    options = [TransferOption(**item) for item in data["options"]]
    constraints = SelectionConstraints(**data["constraints"])
    validate_problem(options, constraints)
    return options, constraints
