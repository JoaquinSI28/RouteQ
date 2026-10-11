"""Regression gates for launch reliability and experiment orchestration."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from main import run_experiment
from qiskit.providers.basic_provider import BasicSimulator
from rutaq.circuits import build_search_circuit, compile_for_qis

ROOT = Path(__file__).resolve().parents[1]


class UpgradeTests(unittest.TestCase):
    def test_qollab_adapter_exports_json_and_circuit(self):
        import main as adapter
        sender = Mock()
        with patch.object(adapter, 'backend', BasicSimulator(seed_simulator=42), create=True), \
                patch.dict(sys.modules, {'js': SimpleNamespace(sendFile=sender)}), \
                contextlib.redirect_stdout(io.StringIO()):
            adapter.main(shots=16, experiment_mode=1)
        self.assertEqual(sender.call_count, 2)
        result_call, circuit_call = sender.call_args_list
        self.assertEqual(result_call.args[:2], ('rutaq_run.json', 'application/json'))
        self.assertEqual(set(json.loads(result_call.args[2])['experiments']), {'uniform_sampling'})
        self.assertEqual(circuit_call.args[:2], ('rutaq_circuit.txt', 'text/plain'))
        self.assertTrue(circuit_call.args[2])

    def test_only_selected_circuits_are_built_and_compiled(self):
        for mode, expected_rounds in ((0, [0, 1]), (1, [0]), (2, [1])):
            with contextlib.redirect_stdout(io.StringIO()), \
                    patch('rutaq.experiment.build_search_circuit', wraps=build_search_circuit) as build, \
                    patch('rutaq.experiment.compile_for_qis', wraps=compile_for_qis) as compile_circuit:
                record, _ = run_experiment(BasicSimulator(seed_simulator=42), shots=16, experiment_mode=mode)
            self.assertEqual([call.args[2] for call in build.call_args_list], expected_rounds)
            self.assertEqual(compile_circuit.call_count, len(expected_rounds))
            for metric in ('circuit_build', 'circuit_compile'):
                self.assertAlmostEqual(record['timings_seconds'][metric],
                                       sum(item['timings_seconds'][metric] for item in record['experiments'].values()))

    def test_iteration_warning_matches_ideal_success(self):
        for deadline, expected_count in ((0, 0), (20, 1), (40, 3), (63, 4)):
            with contextlib.redirect_stdout(io.StringIO()):
                record, _ = run_experiment(BasicSimulator(seed_simulator=42), shots=16,
                                          time_limit_minutes=deadline, experiment_mode=2)
            self.assertEqual(len(record['classical_baseline']['feasible_indices']), expected_count)
            self.assertEqual(bool(record['warnings']), expected_count == 3)
            if expected_count == 3:
                self.assertAlmostEqual(record['experiments']['constraint_grover']['ideal_feasible_probability'], 0)

    def test_cli_import_has_no_execution_side_effects(self):
        process = subprocess.run([sys.executable, '-c', 'import rutaq.__main__'],
                                 cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout, '')

    def test_cli_from_other_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ, PYTHONPATH=str(ROOT))
            process = subprocess.run(
                [sys.executable, '-m', 'rutaq', '--shots', '16', '--experiment', 'uniform'],
                cwd=directory, env=environment, capture_output=True, text=True, timeout=60)
            self.assertEqual(process.returncode, 0, process.stderr)
            record = json.loads((Path(directory)/'rutaq_run.json').read_text())
            self.assertEqual(set(record['experiments']), {'uniform_sampling'})
            self.assertTrue((Path(directory)/'rutaq_run.circuit.txt').is_file())

    def test_invalid_settings_fail_before_build_or_submission(self):
        for settings in ({'shots': 0}, {'scenario': 'missing'}, {'iterations': 4},
                         {'experiment_mode': 9}, {'time_limit_minutes': -1}):
            backend = Mock()
            with patch('rutaq.experiment.build_search_circuit') as build:
                with self.assertRaises(ValueError):
                    run_experiment(backend, **settings)
                build.assert_not_called()
                backend.run.assert_not_called()
