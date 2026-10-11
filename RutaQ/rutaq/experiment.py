"""Qollab entry point for a public-data departure-selection benchmark."""
import json
import math
import statistics
import time
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

import qiskit
from qiskit.providers.jobstatus import JobStatus
from rutaq.domain import parse_problem, classical_baseline
from rutaq.circuits import build_search_circuit, compile_for_qis, make_encoding, encode_option_index

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = {"public": ROOT / "data/public_departures.json", "synthetic": ROOT / "data/transfer_options.json"}


def collect_counts(job, expected_results=2, timeout_seconds=300):
    """Wait for completion and preserve every valid measurement outcome."""
    deadline = time.monotonic()+timeout_seconds
    while True:
        status = job.status()
        if status == JobStatus.DONE:
            break
        if status in (JobStatus.ERROR, JobStatus.CANCELLED):
            raise RuntimeError(f"Quantum job ended with status {status}.")
        if time.monotonic() >= deadline:
            raise TimeoutError("Stopped waiting; the submitted job may still be running.")
        time.sleep(1)
    counts = job.result().get_counts()
    if expected_results == 1 and isinstance(counts, dict):
        counts = [counts]
    if not isinstance(counts, list) or len(counts) != expected_results:
        raise ValueError("Expected one result for every submitted circuit.")
    for result in counts:
        if not result or any(not math.isfinite(float(v)) or v < 0 for v in result.values()) or sum(result.values()) <= 0:
            raise ValueError("Counts must be finite, nonnegative and have a positive total.")
    return [{str(k): float(v) for k, v in item.items()} for item in counts]


def run_experiment(selected_backend, shots=1024, scenario="public", iterations=1, time_limit_minutes=None, experiment_mode=0):
    """Build a raw-attribute oracle, then compare with an independent exact scan."""
    if type(shots) is not int or shots < 1:
        raise ValueError("shots must be a positive integer.")
    if scenario not in SCENARIOS:
        raise ValueError("Unknown scenario; choose public or synthetic.")
    if type(iterations) is not int or not 0 <= iterations <= 3:
        raise ValueError("Use 0 through 3 Grover iterations.")
    if type(experiment_mode) is not int or experiment_mode not in (0, 1, 2):
        raise ValueError("experiment_mode must be 0 (compare), 1 (uniform), or 2 (Grover).")
    path = SCENARIOS[scenario]
    source = json.loads(path.read_text(encoding="utf-8"))
    options, constraints = parse_problem(source)
    if time_limit_minutes is not None:
        constraints = replace(constraints, max_travel_time_minutes=time_limit_minutes)
    encoding = make_encoding(options, constraints)
    backend_name = getattr(selected_backend, "name", "selected_backend")
    backend_name = str(backend_name() if callable(backend_name) else backend_name)
    mode = 2 if backend_name.startswith("ionq") and experiment_mode == 0 else experiment_mode
    indices = [0, 1] if mode == 0 else [mode-1]
    circuits = {}
    timings = {}
    for index in indices:
        start = time.perf_counter()
        logical = build_search_circuit(options, constraints, (0, iterations)[index])
        build_seconds = time.perf_counter()-start
        start = time.perf_counter()
        circuits[index] = compile_for_qis(logical)
        timings[index] = {"circuit_build": build_seconds, "circuit_compile": time.perf_counter()-start}
    build_seconds = sum(timing["circuit_build"] for timing in timings.values())
    compile_seconds = sum(timing["circuit_compile"] for timing in timings.values())
    # Classical answers are computed only after construction, for comparison and scoring.
    reference = classical_baseline(options, constraints)
    samples = []
    for _ in range(100):
        start = time.perf_counter()
        classical_baseline(options, constraints)
        samples.append(time.perf_counter()-start)
    reference["median_validated_full_scan_seconds"] = statistics.median(samples)
    feasible_labels = [encode_option_index(i, encoding.index_bits) for i in reference["feasible_indices"]]
    print("RutaQ | Constraint-aware departure selection")
    seats_limit = "not evaluated" if constraints.min_available_seats is None else str(constraints.min_available_seats)
    print(f"Scenario: {source['data_kind']}; time limit {constraints.max_travel_time_minutes} min; "
          f"minimum seats {seats_limit}; wheelchair confirmation {constraints.requires_wheelchair_access}.")
    if source.get("metadata"):
        meta = source["metadata"]
        print(f"{meta['origin_name']} to {meta['destination_name']}, planning date {meta['planning_date']}, "
              f"ready at {meta['reference_time']}. Elapsed time includes waiting. Scheduled data, not live availability.")
    print("Label  Elapsed min  Seats  Wheelchair confirmed  Offer")
    for i, option in enumerate(options):
        seats_display = str(option.available_seats) if option.available_seats is not None else "n/a"
        print(f"{encode_option_index(i, encoding.index_bits):5}  {option.travel_time_minutes:11}  "
              f"{seats_display:5}  {str(option.wheelchair_accessible):20}  {option.option_id}")
    print(f"Exact classical scan: {reference['full_scan_predicate_evaluations']} checks, "
          f"first match after {reference['first_match_predicate_evaluations']}; feasible labels {feasible_labels}.")
    print(f"Oracle evaluates raw attributes inside the circuit; {encoding.num_qubits} total qubits, "
          f"{encoding.index_bits} index qubits, {iterations} fixed Grover round(s).")
    # Qollab's IonQ gateway permits one single-circuit job per code run.
    selected_circuits = [circuits[i] for i in indices]
    print("Submitting comparison batch..." if mode == 0 else
          "Submitting one circuit; run the other experiment separately for a measured comparison.", flush=True)
    start = time.perf_counter()
    job = selected_backend.run(selected_circuits if mode == 0 else selected_circuits[0], shots=shots)
    results = collect_counts(job, expected_results=len(indices))
    job_seconds = time.perf_counter()-start
    experiments = {}
    n, m = len(options), len(feasible_labels)
    theta = math.asin(math.sqrt(m/n))
    warnings = []
    for i, result in zip(indices, results):
        name = ("uniform_sampling", "constraint_grover")[i]
        rounds = (0, iterations)[i]
        circuit = circuits[i]
        if any(len(label) != encoding.index_bits or set(label)-set("01") for label in result):
            raise ValueError("Backend returned an invalid measured index label.")
        total = sum(result.values())
        if not math.isclose(total, shots):
            raise ValueError("Returned counts do not sum to requested shots.")
        valid = sum(result.get(label, 0) for label in feasible_labels)
        rate = valid/total
        ideal = math.sin((2*rounds+1)*theta)**2
        if i == 1 and ideal < m/n - 1e-12:
            warning = "Chosen Grover iteration count has lower ideal success than uniform sampling."
            warnings.append(warning)
            print(f"Warning: {warning}")
        experiments[name] = {"counts": result, "feasible_selection_rate": rate,
                             "ideal_feasible_probability": ideal, "oracle_queries_per_shot": rounds,
                             "qubits": circuit.num_qubits, "depth": circuit.depth(),
                             "gate_counts": dict(circuit.count_ops()), "timings_seconds": timings[i]}
        print(f"{name}: {valid:g}/{total:g} feasible ({rate:.1%}); ideal {ideal:.1%}; "
              f"CX gates {circuit.count_ops().get('cx', 0)}, depth {circuit.depth()}.")
    job_ids = [str(job.job_id()) if hasattr(job, "job_id") else None]
    record = {"backend": backend_name,
              "job_id": job_ids[0] if len(job_ids) == 1 else None, "job_ids": job_ids,
              "submission_mode": "batch" if mode == 0 else "single_circuit",
              "experiment_mode": mode, "warnings": warnings,
              "noise_model": getattr(getattr(selected_backend, "options", None), "noise_model", None),
              "recorded_at_utc": datetime.now(timezone.utc).isoformat(), "qiskit_version": qiskit.__version__,
              "requested_shots": shots, "data_kind": source["data_kind"], "provenance": source.get("metadata", {}),
              "options": [asdict(o) for o in options], "constraints": asdict(constraints),
              "encoding": asdict(encoding), "classical_baseline": reference, "experiments": experiments,
              "timings_seconds": {"circuit_build": build_seconds, "circuit_compile": compile_seconds,
                                  "backend_job_including_wait": job_seconds},
              "interpretation": "Selection-probability benchmark, not a demonstrated end-to-end quantum advantage. "
                                "Exact classical scanning already solves the input. Explicit data loading is charged in circuit resources."}
    return record, str(selected_circuits[-1].draw(output="text", fold=120))
