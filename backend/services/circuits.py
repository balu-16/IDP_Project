"""Explicit Grover oracles. Qubit zero is the LSB; padding is never hidden."""
import math
import numpy as np


class ResourceLimitError(ValueError):
    pass


def parameters(num_items: int, marked_items):
    if num_items < 1:
        raise ValueError('A circuit needs at least one candidate')
    marked = sorted(set(marked_items))
    if any(not isinstance(i, (int, np.integer)) or i < 0 or i >= num_items for i in marked):
        raise ValueError('Marked index outside candidate range')
    qubits = max(1, (num_items - 1).bit_length())
    space = 2 ** qubits
    count = len(marked)
    if count in (0, space):
        iterations = 0
    else:
        theta = math.asin(math.sqrt(count / space))
        peak = math.pi / (4 * theta) - 0.5
        choices = sorted({max(0, math.floor(peak)), max(0, math.ceil(peak))})
        iterations = max(choices, key=lambda r: (round(math.sin((2*r+1)*theta)**2, 14), -r))
    return qubits, space, marked, iterations


def ideal_probabilities(num_items: int, marked_items, iterations: int | None = None):
    _, space, marked, optimal = parameters(num_items, marked_items)
    r = optimal if iterations is None else iterations
    if r < 0:
        raise ValueError('Iterations must be nonnegative')
    count = len(marked)
    if count == 0 or count == space:
        return np.full(space, 1 / space)
    theta = math.asin(math.sqrt(count / space))
    success = math.sin((2*r + 1)*theta)**2
    probabilities = np.full(space, (1-success)/(space-count))
    probabilities[marked] = success/count
    return probabilities / probabilities.sum()


def phase_oracle(marked_items, num_qubits: int):
    from qiskit import QuantumCircuit
    if num_qubits < 1:
        raise ValueError('At least one address qubit is required')
    _, _, marked, _ = parameters(2**num_qubits, marked_items)
    oracle = QuantumCircuit(num_qubits, name='marked_phase')
    for item in marked:
        zeros = [q for q in range(num_qubits) if not (item >> q) & 1]
        for q in zeros:
            oracle.x(q)
        if num_qubits == 1:
            oracle.z(0)
        else:
            oracle.h(num_qubits-1)
            oracle.mcx(list(range(num_qubits-1)), num_qubits-1)
            oracle.h(num_qubits-1)
        for q in zeros:
            oracle.x(q)
    return oracle


def diffuser(num_qubits: int):
    from qiskit import QuantumCircuit
    circuit = QuantumCircuit(num_qubits, name='diffusion')
    circuit.h(range(num_qubits))
    circuit.compose(phase_oracle([0], num_qubits), inplace=True)
    circuit.h(range(num_qubits))
    # Conventional diffuser up to an irrelevant global phase.
    return circuit


def grover_circuit(num_items, marked_items, iterations=None, oracle=None):
    from qiskit import QuantumCircuit
    qubits, _, marked, optimal = parameters(num_items, marked_items)
    r = optimal if iterations is None else iterations
    if r < 0:
        raise ValueError('Iterations must be nonnegative')
    circuit = QuantumCircuit(qubits)
    circuit.h(range(qubits))
    if r == 0:
        # No amplification: uniform superposition only, no unused oracle.
        return circuit
    marking = phase_oracle(marked, qubits) if oracle is None else oracle
    # If a custom oracle with work registers was supplied, expand circuit.
    if marking.num_qubits != qubits:
        circuit = QuantumCircuit(marking.num_qubits)
        circuit.h(range(qubits))
    address_diffuser = diffuser(qubits)
    for _ in range(r):
        circuit.compose(marking, inplace=True)
        # Diffusion always acts on the address register, including when the
        # oracle carries work qubits (issue 4). Work qubits are untouched.
        circuit.compose(address_diffuser, qubits=list(range(qubits)), inplace=True)
    return circuit


def score_oracle(scores, score_bits: int, threshold: float, max_qubits: int = 18):
    """Lookup -> comparison -> valid AND good phase -> uncompute.

    Scores round to nearest integer (ties to even); threshold uses ceil.
    Work qubits start and finish in zero. No free qRAM or quantum dot product.
    """
    from qiskit import QuantumCircuit
    from qiskit.circuit.library import IntegerComparator
    values = np.asarray(scores, dtype=float)
    if values.ndim != 1 or not len(values) or not np.isfinite(values).all():
        raise ValueError('Expected finite one-dimensional scores')
    if np.any((values < 0) | (values > 1)) or not 0 <= threshold <= 1:
        raise ValueError('Fixed-point scores and threshold must be in [0, 1]')
    if not 1 <= score_bits <= 16:
        raise ValueError('Score precision must be between 1 and 16 bits')
    address, space, _, _ = parameters(len(values), [])
    scale = 2**score_bits-1
    integers = np.rint(values*scale).astype(int)
    threshold_integer = math.ceil(threshold*scale)
    comparator = IntegerComparator(score_bits, threshold_integer, geq=True)
    total = address + score_bits + 2 + comparator.num_ancillas
    if total > max_qubits:
        raise ResourceLimitError(f'{total} total qubits exceeds limit {max_qubits}')
    score = list(range(address, address+score_bits))
    valid, good = address+score_bits, address+score_bits+1
    ancillas = list(range(good+1, total))
    lookup = QuantumCircuit(total, name='classical_score_lookup')
    for index, integer in enumerate(integers):
        zeros = [q for q in range(address) if not (index >> q) & 1]
        for q in zeros:
            lookup.x(q)
        lookup.mcx(list(range(address)), valid)
        for bit, target in enumerate(score):
            if (int(integer) >> bit) & 1:
                lookup.mcx(list(range(address)), target)
        for q in zeros:
            lookup.x(q)
    oracle = QuantumCircuit(total, name='score_threshold_phase')
    oracle.compose(lookup, inplace=True)
    comparison_qubits = score + [good] + ancillas
    oracle.compose(comparator, qubits=comparison_qubits, inplace=True)
    oracle.cz(valid, good)
    oracle.compose(comparator.inverse(), qubits=comparison_qubits, inplace=True)
    oracle.compose(lookup.inverse(), inplace=True)
    marked = np.flatnonzero(integers >= threshold_integer).tolist()
    return oracle, {'address_qubits': address, 'score_qubits': score_bits,
                    'work_qubits': total-address-score_bits, 'total_qubits': total,
                    'space': space, 'quantized_scores': integers.tolist(),
                    'threshold_integer': threshold_integer, 'marked_indices': marked,
                    'quantization_changed_marks': int(np.sum((values >= threshold) != (integers >= threshold_integer)))}
