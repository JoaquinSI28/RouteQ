"""Reversible data loading, numeric constraint evaluation and index amplification."""
from dataclasses import dataclass
from qiskit import QuantumCircuit, transpile
from qiskit.synthesis import synth_integer_comparator_2s
from rutaq.domain import validate_problem


@dataclass(frozen=True)
class Encoding:
    index_bits: int
    time_bits: int
    seat_bits: int

    @property
    def num_qubits(self):
        return self.index_bits + self.time_bits + self.seat_bits + 3 + max(self.time_bits-1, self.seat_bits-1)

    def registers(self):
        index = list(range(self.index_bits))
        start = self.index_bits
        time = list(range(start, start+self.time_bits))
        start += self.time_bits
        seats = list(range(start, start+self.seat_bits))
        start += self.seat_bits
        accessible, time_ok, seats_ok = start, start+1, start+2
        work = list(range(start+3, self.num_qubits))
        return index, time, seats, accessible, time_ok, seats_ok, work


def make_encoding(options, constraints):
    validate_problem(options, constraints)
    return Encoding((len(options)-1).bit_length(),
                    max(1, max([o.travel_time_minutes for o in options]+[constraints.max_travel_time_minutes]).bit_length()),
                    max(1, max([o.available_seats or 0 for o in options]+[constraints.min_available_seats or 0]).bit_length()))


def encode_option_index(option_index, index_bits=2):
    if type(option_index) is not int or not 0 <= option_index < 2**index_bits:
        raise ValueError("Index does not fit the basis encoding.")
    return format(option_index, f"0{index_bits}b")


def build_data_loader(options, encoding):
    """XOR raw attributes into zeroed feature registers; no feasibility labels are loaded."""
    circuit = QuantumCircuit(encoding.num_qubits, name="load_attributes")
    index, times, seats, accessible, *_ = encoding.registers()
    for i, option in enumerate(options):
        zero_controls = [q for bit, q in enumerate(index) if not (i >> bit) & 1]
        if zero_controls:
            circuit.x(zero_controls)
        values = [(times, option.travel_time_minutes), (seats, option.available_seats or 0), ([accessible], int(option.wheelchair_accessible))]
        for register, value in values:
            for bit, target in enumerate(register):
                if (value >> bit) & 1:
                    circuit.mcx(index, target)
        if zero_controls:
            circuit.x(zero_controls)
    return circuit


def build_constraint_oracle(options, constraints):
    """Phase-mark the conjunction of numeric comparisons and wheelchair confirmation.

    The builder takes raw offers and constraints, never a marked index or solution count.
    Feature, comparison and workspace registers return to zero after each query.
    """
    encoding = make_encoding(options, constraints)
    _, times, seats, accessible, time_ok, seats_ok, work = encoding.registers()
    loader = build_data_loader(options, encoding)
    compare = QuantumCircuit(encoding.num_qubits, name="evaluate_constraints")
    compare.compose(synth_integer_comparator_2s(encoding.time_bits, constraints.max_travel_time_minutes+1, geq=False),
                    qubits=times+[time_ok]+work[:encoding.time_bits-1], inplace=True)
    if constraints.min_available_seats is None:
        compare.x(seats_ok)
    else:
        compare.compose(synth_integer_comparator_2s(encoding.seat_bits, constraints.min_available_seats, geq=True),
                        qubits=seats+[seats_ok]+work[:encoding.seat_bits-1], inplace=True)
    oracle = QuantumCircuit(encoding.num_qubits, name="constraint_oracle")
    oracle.compose(loader, inplace=True)
    oracle.compose(compare, inplace=True)
    if constraints.requires_wheelchair_access:
        oracle.h(accessible)
        oracle.mcx([time_ok, seats_ok], accessible)
        oracle.h(accessible)
    else:
        oracle.cz(time_ok, seats_ok)
    oracle.compose(compare.inverse(), inplace=True)
    oracle.compose(loader.inverse(), inplace=True)
    return oracle


def apply_index_diffusion(circuit, index):
    """Amplify index amplitudes, with an irrelevant overall minus sign."""
    circuit.h(index)
    circuit.x(index)
    circuit.h(index[-1])
    circuit.mcx(index[:-1], index[-1])
    circuit.h(index[-1])
    circuit.x(index)
    circuit.h(index)


def build_search_circuit(options, constraints, iterations=1):
    """Use a fixed round count; do not use classical feasible labels to build the circuit."""
    if type(iterations) is not int or not 0 <= iterations <= 3:
        raise ValueError("Use 0 through 3 Grover iterations.")
    encoding = make_encoding(options, constraints)
    circuit = QuantumCircuit(encoding.num_qubits, encoding.index_bits, name=f"grover_{iterations}_rounds")
    index, *_ = encoding.registers()
    circuit.h(index)
    if iterations:
        oracle = build_constraint_oracle(options, constraints)
        for _ in range(iterations):
            circuit.compose(oracle, inplace=True)
            apply_index_diffusion(circuit, index)
    circuit.measure(index, list(range(encoding.index_bits)))
    return circuit


def compile_for_qis(circuit):
    """Lower comparators and controlled gates to H, X, RZ and CX for QIS execution."""
    return transpile(circuit, basis_gates=["h", "x", "rz", "cx"], optimization_level=1, seed_transpiler=42)
