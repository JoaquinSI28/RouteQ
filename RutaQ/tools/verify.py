"""Run local regression gates and write evidence; no remote jobs are submitted."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def invoke(arguments, directory):
    environment = dict(os.environ, PYTHONPATH=str(ROOT))
    result = subprocess.run([sys.executable, *arguments], cwd=directory, env=environment,
                            capture_output=True, text=True, timeout=180)
    require(result.returncode == 0, result.stdout + result.stderr)
    return result.stdout + result.stderr


def check_record(record, expected_names):
    require(set(record['experiments']) == set(expected_names), 'Wrong experiments exported')
    shots = record['requested_shots']
    feasible = record['classical_baseline']['feasible_indices']
    width = record['encoding']['index_bits']
    feasible_labels = [format(index, f'0{width}b') for index in feasible]
    fraction = len(feasible)/len(record['options'])
    should_warn = False
    for name, experiment in record['experiments'].items():
        counts = experiment['counts']
        require(all(len(label) == width and set(label) <= set('01') for label in counts), 'Invalid labels')
        require(all(math.isfinite(value) and value >= 0 for value in counts.values()), 'Invalid counts')
        require(sum(counts.values()) == shots, 'Shot total changed')
        measured = sum(counts.get(label, 0) for label in feasible_labels)/shots
        require(math.isclose(measured, experiment['feasible_selection_rate'], abs_tol=1e-12), 'Wrong measured rate')
        rounds = experiment['oracle_queries_per_shot']
        expected = math.sin((2*rounds+1)*math.asin(math.sqrt(fraction)))**2
        require(math.isclose(expected, experiment['ideal_feasible_probability'], abs_tol=1e-12), 'Wrong ideal rate')
        tolerance = 6*math.sqrt(expected*(1-expected)/shots) + 1/shots
        require(abs(measured-expected) <= tolerance, 'Measurements disagree with ideal probability')
        should_warn |= name == 'constraint_grover' and expected < fraction-1e-12
    require(bool(record['warnings']) == should_warn, 'Missing or incorrect overshoot warning')
    for metric in ('circuit_build', 'circuit_compile'):
        total = sum(experiment['timings_seconds'][metric] for experiment in record['experiments'].values())
        require(total >= 0 and math.isclose(total, record['timings_seconds'][metric]), 'Incorrect timing aggregation')


def check_baseline(record, baseline):
    for key in ('options', 'constraints', 'encoding', 'data_kind'):
        require(record[key] == baseline[key], f'Baseline changed: {key}')
    require(record['classical_baseline']['feasible_indices'] == baseline['feasible_indices'], 'Solutions changed')
    for name, experiment in record['experiments'].items():
        for key, expected in baseline['experiments'][name].items():
            actual = experiment[key]
            if isinstance(expected, float):
                require(math.isclose(actual, expected, abs_tol=1e-12), f'{name}: {key} changed')
            else:
                require(actual == expected, f'{name}: {key} changed; review compiler version and circuit changes')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'verification-report.json')
    args = parser.parse_args()
    report = {'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
              'python_version': sys.version, 'seed': 42, 'passed': False, 'gates': [],
              'remote_validation': 'Not run: live Qollab and IonQ require separate verification.',
              'source_sha256': {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                for pattern in ('*.py', 'rutaq/*.py', 'tests/*.py', 'tools/*.py',
                                                'data/*.json', 'tests/baseline.json', 'requirements.txt')
                                for path in sorted(ROOT.glob(pattern))}}
    try:
        log = invoke(['-m', 'unittest', 'discover', '-s', str(ROOT/'tests'), '-v'], ROOT)
        report['gates'].append({'name': 'unit_and_adapter_tests', 'passed': True, 'log': log})
        print('PASS: unit and adapter tests', flush=True)
        baseline = json.loads((ROOT/'tests/baseline.json').read_text())
        with tempfile.TemporaryDirectory(prefix='rutaq-verify-') as directory:
            output = Path(directory)/'run.json'

            def run_case(name, scenario, mode, cwd, extra=(), compare_baseline=False):
                invoke(['-m', 'rutaq', '--scenario', scenario, '--experiment', mode, '--shots', '256',
                        '--seed', '42', '--output', str(output), *extra], cwd)
                record = json.loads(output.read_text())
                expected = {'compare': ['uniform_sampling', 'constraint_grover'],
                            'uniform': ['uniform_sampling'], 'grover': ['constraint_grover']}[mode]
                check_record(record, expected)
                require(output.with_suffix('.circuit.txt').stat().st_size > 0, 'Missing circuit export')
                require(record['simulator_seed'] == 42, 'Simulator seed not recorded')
                if compare_baseline:
                    check_baseline(record, baseline[scenario])
                report['gates'].append({'name': name, 'passed': True, 'record': record})
                print(f'PASS: {name}', flush=True)

            for location, cwd in (('project', ROOT), ('external', directory)):
                for scenario in ('public', 'synthetic'):
                    for mode in ('compare', 'uniform', 'grover'):
                        run_case(f'{location}/{scenario}/{mode}', scenario, mode, cwd, compare_baseline=True)
            for deadline in (0, 20, 30, 40, 63):
                for rounds in range(4):
                    run_case(f'sweep/deadline={deadline}/iterations={rounds}', 'public', 'grover', directory,
                             ('--time-limit', str(deadline), '--iterations', str(rounds)))
        report['passed'] = True
    except Exception as error:
        report['error'] = str(error)
        print(f'FAIL: {error}', file=sys.stderr)
    args.output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(f"{'PASS' if report['passed'] else 'FAIL'}: local verification; report: {args.output}")
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
