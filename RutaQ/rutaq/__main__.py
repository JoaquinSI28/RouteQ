"""Run the same benchmark locally with Qiskit's ideal BasicSimulator."""
import argparse
import json
from pathlib import Path
from qiskit.providers.basic_provider import BasicSimulator
from rutaq.experiment import run_experiment

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=["public", "synthetic"], default="public")
    parser.add_argument("--shots", type=int, default=1024)
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--time-limit", type=int, default=None)
    parser.add_argument("--experiment", choices=["compare", "uniform", "grover"], default="compare")
    parser.add_argument("--output", default="rutaq_run.json")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()
    record, circuit = run_experiment(BasicSimulator(seed_simulator=args.seed), args.shots, args.scenario, args.iterations, args.time_limit, {"compare": 0, "uniform": 1, "grover": 2}[args.experiment])
    record["simulator_seed"] = args.seed
    Path(args.output).write_text(json.dumps(record, indent=2)+"\n", encoding="utf-8")
    Path(args.output).with_suffix(".circuit.txt").write_text(circuit, encoding="utf-8")
    print(f"Saved measurement evidence to {args.output}.")


if __name__ == "__main__":
    main()
