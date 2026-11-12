# RutaQ — Constraint-Aware Departure Selection

A passenger in Helsinki is ready to leave at 08:00. They have 20 minutes to reach their destination and need wheelchair access. Four departures serve the same stops. Which ones meet both requirements, and how often does a quantum search circuit return one of them?

RutaQ turns this timetable question into a reproducible **Python and Qiskit** experiment. Team **Qbitos** presented the project in the student track of the **Qollab and IonQ Quantum Hackathon 2026** through the UNICEN node.

[Try the interactive demo](https://rutaq-landing.vercel.app/) · [Watch the 2:45 walkthrough](https://rutaq-landing.vercel.app/demo.html) · [View the project on Qollab](https://qollab.xyz/p/01a1267e-7c03-7c10-b573-5aded6342a8c?v=v1.1) · [Read the technical guide](RutaQ/README.md)

## The Helsinki example

The public scenario uses the first four eligible HSL route 1001 departures from Telakkakatu to Lasipalatsi on 14 October 2026. Each journey takes 13 minutes on board. A passenger's deadline includes the wait at the origin, so later departures can take the same time on board and still arrive too late.

| Index | Departure | Arrival | Minutes since 08:00 | Within 20 minutes? |
| --- | --- | --- | ---: | --- |
| 00 | 08:01 | 08:14 | 14 | Yes |
| 01 | 08:11 | 08:24 | 24 | No |
| 10 | 08:21 | 08:34 | 34 | No |
| 11 | 08:31 | 08:44 | 44 | No |

The timetable confirms wheelchair access for all four trips and both stops. The deadline therefore determines the answer in this particular sample. Separate tests exercise the accessibility filter. Seat availability is evaluated using synthetic data because the public timetable has no live seat counts. [Scenario data](RutaQ/data/public_departures.json) · [Underlying GTFS rows](RutaQ/data/source_rows.json)

## Try changing the deadline

Open the [interactive lab](https://rutaq-landing.vercel.app/#lab), select **Public schedule**, keep wheelchair access enabled and set **one Grover round**. Change only the arrival deadline and watch the probability of measuring any feasible departure.

| Deadline | Feasible departures | Uniform sampling | One Grover round, ideal model |
| --- | ---: | ---: | ---: |
| 20 minutes | 1 of 4 | 25% | 100% |
| 30 minutes | 2 of 4 | 50% | 50% |
| 40 minutes | 3 of 4 | 75% | 0% |

At 40 minutes, only the 08:31 departure misses the deadline. With three solutions, a single round of phase marking and diffusion concentrates the ideal measurement probability on that one failing departure. The number of feasible options matters when choosing how many rounds to run. The browser computes these ideal probabilities locally.

## How the circuit makes the decision

1. Two index qubits encode the four departures. Hadamard gates give each index an equal starting probability.
2. Reversible gates load the selected departure's attributes into working registers. The oracle compares elapsed time with the deadline and evaluates the enabled accessibility and capacity requirements.
3. A phase flip marks each index that satisfies the conditions. Reversing the checks and the load clears the working registers while preserving the phase information.
4. Grover diffusion changes the amplitudes of the indices. Measuring the index register yields a departure. A separate exact classical scan determines which outcomes count as successes.

Explicit data loading contributes to the circuit cost. The reported default compilation uses **17 qubits**, including the two index qubits, **285 CX gates**, and **depth 404**.

## What the simulations measured

Each entry below counts how many of 1,024 measurements returned the single feasible departure with the 20-minute deadline. The two historical cloud runs predate the execution-module refactor. The seeded local run provides a reference for the later package.

| Environment | Uniform sampling | One Grover round |
| --- | ---: | ---: |
| Qollab ideal simulator, historical run | 269 / 1,024 (26.3%) | 1,024 / 1,024 (100%) |
| IonQ Aria 1 noise model on Qollab, historical run | 254 / 1,024 (24.8%) | 541 / 1,024 (52.8%) |
| Local Qiskit simulation, seed 42 | 268 / 1,024 (26.2%) | 1,024 / 1,024 (100%) |

In the Aria 1 noise simulation, the measured success rate increased by **28 percentage points** over uniform sampling. This is one simulated comparison on one timetable. An exact classical scan finds the first feasible departure in **one check** in this ordering and identifies every feasible departure in **four checks**. The experiment measures selection probability and circuit resources. Establishing a runtime advantage or a passenger benefit would require different evidence. [Cloud evidence package](https://rutaq-landing.vercel.app/assets/RutaQ-evidence.zip) · [Seeded local result](https://rutaq-landing.vercel.app/assets/public-run.json)

## Run locally

From a terminal on macOS or Linux, clone the repository and enter the Python project directory.

~~~sh
git clone https://github.com/JoaquinSI28/RouteQ.git
cd RouteQ/RutaQ
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m rutaq --scenario public --shots 1024 --iterations 1 --seed 42
~~~

To verify the implementation, run the following command from the same directory. It covers 20 unit and adapter tests, 12 CLI checks, and 20 combinations of deadlines and iteration counts. The command returns a nonzero exit status if a check fails. [Recorded verification report](https://rutaq-landing.vercel.app/assets/verification-report.json)

~~~sh
python tools/verify.py
~~~

## Where to find the implementation

| File | What to look for |
| --- | --- |
| [Domain model](RutaQ/rutaq/domain.py) | Input validation, feasibility rules and the exact classical reference |
| [Circuit construction](RutaQ/rutaq/circuits.py) | Reversible loading, constraint evaluation, uncomputation and diffusion |
| [Experiment runner](RutaQ/rutaq/experiment.py) | Compilation, execution, scoring and output records |
| [Qollab entry point](RutaQ/main.py) | Running and exporting an experiment through Qollab |
| [GTFS extraction](RutaQ/tools/extract_hsl.py) | Reproducing the public input and checking its source hash |

The code is distributed under the [MIT license](RutaQ/LICENSE). The HSL-derived timetable data is credited to Helsinki Region Transport (HSL), © 2026, under CC BY 4.0. [HSL open data](https://www.hsl.fi/en/opendata)
