"""Verify numeric marking, clean workspace, unsupported data and fair comparisons."""
import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np
from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector
from qiskit.providers.jobstatus import JobStatus
from main import collect_counts
from rutaq.domain import TransferOption, SelectionConstraints, classical_baseline, load_problem, validate_problem
from rutaq.circuits import build_constraint_oracle, build_search_circuit, make_encoding, compile_for_qis

ROOT = Path(__file__).resolve().parents[1]


class CompletedJob:
    def __init__(self, counts): self.counts = counts
    def status(self): return JobStatus.DONE
    def result(self): return self
    def get_counts(self): return self.counts


class RutaQTests(unittest.TestCase):
    def setUp(self):
        self.options = [TransferOption('a', 1, 3, False), TransferOption('b', 5, 3, True),
                        TransferOption('c', 3, 2, True), TransferOption('d', 2, 1, True)]
        self.constraints = SelectionConstraints(3, 2, True)

    def assert_oracle(self, options, constraints):
        encoding = make_encoding(options, constraints)
        state = QuantumCircuit(encoding.num_qubits)
        state.h(list(range(encoding.index_bits)))
        state.compose(build_constraint_oracle(options, constraints), inplace=True)
        output = Statevector.from_instruction(state).data
        expected = np.zeros(2**encoding.num_qubits, dtype=complex)
        feasible = classical_baseline(options, constraints)['feasible_indices']
        for i in range(len(options)):
            expected[i] = (-1 if i in feasible else 1)/np.sqrt(len(options))
        # Every feature/comparison/work qubit is zero; otherwise amplitude leaks above N.
        np.testing.assert_allclose(output, expected, atol=1e-10)

    def test_numeric_oracle_and_clean_workspace(self):
        self.assert_oracle(self.options, self.constraints)

    def test_each_candidate_can_be_the_solution(self):
        for index in range(4):
            opts = [replace(o, travel_time_minutes=1, available_seats=3, wheelchair_accessible=i==index)
                    for i, o in enumerate(self.options)]
            self.assert_oracle(opts, self.constraints)
            circuit = build_search_circuit(opts, self.constraints).remove_final_measurements(inplace=False)
            state = Statevector.from_instruction(circuit)
            expected = np.zeros(2**circuit.num_qubits)
            expected[index] = 1
            np.testing.assert_allclose(state.probabilities(), expected, atol=1e-10)

    def test_threshold_boundaries(self):
        self.assert_oracle(self.options, replace(self.constraints, max_travel_time_minutes=2))
        self.assert_oracle(self.options, replace(self.constraints, min_available_seats=3))
        self.assert_oracle(self.options, replace(self.constraints, max_travel_time_minutes=0))
        self.assert_oracle(self.options, replace(self.constraints, max_travel_time_minutes=7, min_available_seats=0))

    def test_optional_constraints_and_unknown_seats(self):
        opts = [replace(o, available_seats=None) for o in self.options]
        constraints = replace(self.constraints, min_available_seats=None, requires_wheelchair_access=False)
        self.assert_oracle(opts, constraints)
        with self.assertRaises(ValueError): validate_problem(opts, self.constraints)

    def test_reordered_data(self):
        self.assert_oracle(list(reversed(self.options)), self.constraints)

    def test_zero_multiple_and_all_solutions(self):
        cases = [(0, 0), (3, 3), (7, 4)]
        opts = [replace(o, available_seats=None, wheelchair_accessible=True) for o in self.options]
        for limit, m in cases:
            constraints = SelectionConstraints(limit, None, False)
            self.assert_oracle(opts, constraints)
            for rounds in (0, 1, 2):
                circuit = build_search_circuit(opts, constraints, rounds).remove_final_measurements(inplace=False)
                probabilities = Statevector.from_instruction(circuit).probabilities()
                valid = classical_baseline(opts, constraints)['feasible_indices']
                theta = np.arcsin(np.sqrt(m/4))
                self.assertAlmostEqual(sum(probabilities[i] for i in valid), np.sin((2*rounds+1)*theta)**2, places=9)
                self.assertAlmostEqual(sum(probabilities[:4]), 1, places=9)

    def test_loading_supports_sixteen_candidates(self):
        opts = [TransferOption(str(i), i%2, None, i==11) for i in range(16)]
        constraints = SelectionConstraints(1, None, True)
        self.assert_oracle(opts, constraints)

    def test_qis_compilation_preserves_probabilities(self):
        logical = build_search_circuit(self.options, self.constraints)
        compiled = compile_for_qis(logical)
        self.assertLessEqual(set(compiled.count_ops()), {'h', 'x', 'rz', 'cx', 'measure'})
        for circuit in (logical, compiled):
            state = Statevector.from_instruction(circuit.remove_final_measurements(inplace=False))
            self.assertAlmostEqual(state.probabilities()[2], 1, places=9)

    def test_builder_does_not_call_classical_solver(self):
        with patch('rutaq.domain.classical_baseline', side_effect=AssertionError('classical solver used')):
            build_constraint_oracle(self.options, self.constraints)
            build_search_circuit(self.options, self.constraints)

    def test_exact_classical_baseline(self):
        result = classical_baseline(self.options, self.constraints)
        self.assertEqual(result['feasible_indices'], [2])
        self.assertEqual(result['full_scan_predicate_evaluations'], 4)
        self.assertEqual(result['first_match_predicate_evaluations'], 3)
        self.assertEqual(result['expected_first_match_checks_random_order'], 2.5)

    def test_public_extract_has_traceable_common_journey(self):
        options, constraints = load_problem(ROOT/'data/public_departures.json')
        evidence = json.loads((ROOT/'data/source_rows.json').read_text())
        self.assertEqual([o.travel_time_minutes for o in options], [14, 24, 34, 44])
        self.assertIsNone(constraints.min_available_seats)
        self.assertEqual(classical_baseline(options, constraints)['feasible_indices'], [0])
        self.assertEqual(evidence['metadata']['planning_date'], '2026-10-14')
        for option, row in zip(options, evidence['rows']):
            self.assertEqual(option.option_id, row['trip']['trip_id'])
            self.assertEqual(row['boarding']['stop_id'], '1050417')
            self.assertEqual(row['alighting']['stop_id'], '1020444')
            self.assertEqual(row['trip']['wheelchair_accessible'], '1')
            self.assertEqual(row['origin_stop']['wheelchair_boarding'], '1')
            self.assertEqual(row['destination_stop']['wheelchair_boarding'], '1')

    def test_bounded_input_is_not_silently_truncated(self):
        invalid = [self.options[:3], [replace(self.options[0], travel_time_minutes=64)]+self.options[1:],
                   [replace(self.options[0], available_seats=8)]+self.options[1:],
                   [replace(self.options[0], wheelchair_accessible='unknown')]+self.options[1:]]
        for options in invalid:
            with self.assertRaises(ValueError): validate_problem(options, self.constraints)
        for value in (-1, True, 4):
            with self.assertRaises(ValueError): build_search_circuit(self.options, self.constraints, value)

    def test_ionq_adapter_submits_one_circuit_and_records_only_that_experiment(self):
        from main import run_experiment
        from qiskit.providers.basic_provider import BasicSimulator
        from contextlib import redirect_stdout
        from io import StringIO
        class SingleCircuitBackend:
            name = "ionq_test_adapter"
            def __init__(self): self.calls = []
            def run(self, circuit, shots):
                if isinstance(circuit, list): raise AssertionError("Only a single circuit is allowed.")
                self.calls.append(circuit)
                return BasicSimulator().run(circuit, shots=shots, seed_simulator=42)
        for mode, expected in ((0, "constraint_grover"), (1, "uniform_sampling"), (2, "constraint_grover")):
            backend = SingleCircuitBackend()
            with redirect_stdout(StringIO()):
                record, drawing = run_experiment(backend, shots=16, experiment_mode=mode)
            self.assertEqual(len(backend.calls), 1)
            self.assertEqual(set(record["experiments"]), {expected})
            self.assertEqual(record["submission_mode"], "single_circuit")
            self.assertEqual(sum(record["experiments"][expected]["counts"].values()), 16)
            self.assertEqual(drawing, str(backend.calls[0].draw(output="text", fold=120)))

    def test_counts_preserve_rare_results_and_reject_invalid_weights(self):
        counts = [{'00': 1, '10': 1023}, {'00': 2, '10': 1022}]
        self.assertEqual(collect_counts(CompletedJob(counts)), counts)
        self.assertEqual(collect_counts(CompletedJob(counts[0]), expected_results=1), [counts[0]])
        for values in ({'10': 100}, [{}, {'10': 100}], [{'10': -1}, {'10': 100}],
                       [{'10': float('nan')}, {'10': 100}], [{'10': float('inf')}, {'10': 100}]):
            with self.assertRaises(ValueError): collect_counts(CompletedJob(values))


if __name__ == '__main__': unittest.main()
