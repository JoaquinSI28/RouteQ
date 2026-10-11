# RutaQ

RutaQ uses a reversible Grover oracle to select a scheduled departure that meets a deadline and has confirmed wheelchair accessibility. It compares measured success with uniform sampling and an exact classical scan.

## Example

A passenger is ready at 08:00 on 14 October 2026 and needs to travel from Telakkakatu to Lasipalatsi within 20 minutes. The public example contains the first four eligible HSL route `1001` departures, selected without filtering by feasibility.

| Label (`q1q0`) | Departure | Arrival | Minutes from 08:00 | Wheelchair confirmed | Feasible |
|---|---|---|---:|---|---|
| `00` | 08:01 | 08:14 | 14 | Yes | Yes |
| `01` | 08:11 | 08:24 | 24 | Yes | No |
| `10` | 08:21 | 08:34 | 34 | Yes | No |
| `11` | 08:31 | 08:44 | 44 | Yes | No |

Elapsed time includes waiting; each journey lasts 13 minutes on board. All four trips and both stops have confirmed accessibility, so the deadline determines feasibility here. Separate tests exercise accessibility rejection. GTFS provides no live seat availability; seating is disabled in this example and tested with synthetic data.

The snapshot comes from [HSL open data](https://www.hsl.fi/en/opendata), © HSL 2026, CC BY 4.0. The [GTFS archive](https://infopalvelut.storage.hsldev.com/gtfs/hsl.zip) was downloaded on 11 October 2026, feed version `2026-10-10 06:50:57`. [Scenario metadata](data/public_departures.json) records selection rules; [source rows](data/source_rows.json) preserve the underlying records. These schedules do not guarantee actual arrivals or current vehicle conditions.

## Run locally

From the project root:

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m rutaq --scenario public --shots 1024 --iterations 1 --output public-run.json
python -m rutaq --scenario synthetic --shots 1024 --iterations 1 --output synthetic-run.json
python -m rutaq --scenario public --time-limit 30 --iterations 0 --output two-feasible-run.json
python -m rutaq --scenario public --experiment grover --output grover-only.json
```

Add `--seed 42` for repeatable local sampling. The CLI exports a JSON record and a compiled circuit drawing. When launching elsewhere, put the project root on `PYTHONPATH`; input paths resolve relative to the source, and output paths relative to the working directory.

Inputs support 2, 4, 8 or 16 offers, integer times from 0 to 63 minutes, and known seating values from 0 to 7. Missing seating is allowed only when that constraint is disabled. Grover iterations range from 0 to 3.

## Verify changes

```bash
python tools/verify.py
```

The command runs 20 unit/adapter tests, 12 CLI checks and 20 deadline/iteration cases. It prints PASS/FAIL and exits unsuccessfully if any check fails.

## How the circuit works

1. Prepare an equal superposition of offer indices.
2. Reversibly load raw time, seating and accessibility attributes.
3. Evaluate the enabled constraints with comparator and logic gates.
4. Change the phase of indices that meet every requirement.
5. Reverse the computation and loading, returning working registers to zero.
6. Apply diffusion and measure the index register.

The oracle receives attributes and constraints without a preselected answer or classical solution count. The classical scan runs afterward for comparison and scoring. The implementation follows [Grover's search algorithm](https://arxiv.org/abs/quant-ph/9605043).

The public circuit uses 17 qubits, including two index qubits. Explicit data loading contributes to its gate count and depth. Only requested experiments are built and compiled; records contain per-experiment timings and their totals.

## Recorded results

These cloud runs used the version before the orchestration upgrade, on 11 October 2026, with 1,024 shots per experiment.

| Environment | Uniform feasible outcomes | Grover feasible outcomes |
|---|---:|---:|
| Qollab ideal simulator in Chrome | 269 / 1,024 (26.3%) | 1,024 / 1,024 (100%) |
| IonQ Aria 1 noise simulator through Qollab | 254 / 1,024 (24.8%) | 541 / 1,024 (52.8%) |

The ideal probabilities are 25% and 100%. The noisy runs show an increase of about 28 percentage points, or 2.13 times the uniform selection probability. The recorded compilation has 285 CX gates and depth 404.

## Limits and failure case

An exact classical scan finds the answer with four full-scan checks, or one first-match check in this input order. A sorted timetable can exploit its ordering. This four-offer example does not establish a practical quantum advantage, route optimality, economic benefit or improved passenger outcomes.

One Grover round works for the public example's single feasible offer. At a 40-minute deadline, three offers pass, but that same round gives zero ideal success by amplifying the failing offer. The current code warns when the chosen round count has lower ideal success than uniform sampling; the diagnostic does not select a better round count.

All recorded quantum runs are simulations. One noisy run per method cannot establish performance across workloads or hardware. Build, compilation and simulation times are separate from classical scan timing and do not demonstrate hardware speedup. The historical browser scan median of zero reflects insufficient timer resolution.

## Run on Qollab

Upload the project with `main.py` at the root. The entry point exposes `shots`, `time_limit_minutes`, `iterations` and `experiment_mode`; defaults use the public scenario, 1,024 shots, a 20-minute limit and one round.

| Mode | Built-in simulator | IonQ backend |
|---|---|---|
| `0` | Compare both experiments | Grover only |
| `1` | Uniform only | Uniform only |
| `2` | Grover only | Grover only |

The IonQ gateway accepts one circuit and one job per code run, so comparison requires two runs. Download the JSON and circuit exports from each.

## Code layout

| Path | Responsibility |
|---|---|
| `rutaq/domain.py` | Validation, feasibility and classical comparison |
| `rutaq/circuits.py` | Loading, constraint evaluation, uncomputation and amplification |
| `rutaq/experiment.py` | Compilation, execution, scoring and result records |
| `main.py` | Qollab entry point and exports |
| `rutaq/__main__.py` | Local CLI |
| `data/` | Public extract, source rows and synthetic example |
| `tests/` | Correctness, boundary and adapter checks |
| `tools/verify.py` | Local verification and sensitivity sweep |
| `tools/extract_hsl.py` | Reproducible extraction with a SHA-256 check |

The 75 MB source ZIP is not bundled; source rows and metadata allow inspection without downloading it.

## Attribution

Code and documentation are MIT-licensed. HSL-derived data retain CC BY 4.0 attribution. AI assistance was used for development and documentation. This effort is supported by Qollab & IonQ for the Quantum Impact track at UNICEN. Check the [official submission requirements](https://qollab.xyz/programs/hackathon/terms) before publishing; this package does not establish acceptance or track eligibility.
