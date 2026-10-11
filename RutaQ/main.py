"""Qollab adapter for the shared departure-selection experiment."""
import json
from rutaq.experiment import collect_counts, run_experiment


def main(shots: int = 1024, time_limit_minutes: int = 20, iterations: int = 1, experiment_mode: int = 0):
    """Qollab supplies the selected global backend and calls this function."""
    record, circuit = run_experiment(backend, shots, iterations=iterations, time_limit_minutes=time_limit_minutes, experiment_mode=experiment_mode)
    print("No end-to-end speedup, optimal routing or physical hardware execution is established.")
    from js import sendFile
    sendFile("rutaq_run.json", "application/json", json.dumps(record, indent=2))
    sendFile("rutaq_circuit.txt", "text/plain", circuit)
    print("Complete. Download the unfiltered results and full compiled circuit.")
