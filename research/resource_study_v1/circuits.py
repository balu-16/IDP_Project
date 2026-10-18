"""Native reversible constraints and quadratic improvement, with clean workspace."""
from __future__ import annotations

import math
import time

import numpy as np
from qiskit import QuantumCircuit, QuantumRegister, AncillaRegister, transpile
from qiskit.circuit.library import IntegerComparator, QuadraticForm, StatePreparation

from .problem import OracleProblem


def counter(m, width, members):
    circuit = QuantumCircuit(m + width, name="count")
    for source in members:
        # Controlled increment, from the most significant bit downwards.
        for bit in reversed(range(1, width)):
            circuit.mcx([source] + list(range(m, m+bit)), m+bit)
        circuit.cx(source, m)
    return circuit


def oracle(problem: OracleProblem):
    m, w, c = problem.m, problem.width, problem.count_width
    decision = QuantumRegister(m, "tail")
    value = QuantumRegister(w, "signed_value")
    count = QuantumRegister(c, "count")
    carry = AncillaRegister(c-1, "comparison_workspace")
    flags = AncillaRegister(4, "constraint_flags")
    compute = QuantumCircuit(decision, value, count, carry, flags, name="compute")
    quadratic = QuadraticForm(w, problem.quadratic.tolist(), problem.linear.tolist(),
                              problem.offset, little_endian=True)
    compute.compose(quadratic, [*decision, *value], inplace=True)
    # Cardinality is checked even outside the fixed-weight preparation domain.
    for condition, members, flag in [
            ("equal3", list(range(m)), flags[0]),
            (3, problem.groups[0], flags[1]),
            (2, problem.groups[1], flags[2]),
            (1, problem.groups[2], flags[3])]:
        addition = counter(m, c, members)
        compute.compose(addition, [*decision, *count], inplace=True)
        if condition == "equal3":
            zeros = [i for i in range(c) if not (3 >> i & 1)]
            for i in zeros:
                compute.x(count[i])
            compute.mcx(list(count), flag)
            for i in zeros:
                compute.x(count[i])
        else:
            comparator = IntegerComparator(c, int(condition), geq=True)
            compute.compose(comparator, [*count, flag, *carry], inplace=True)
        compute.compose(addition.inverse(), [*decision, *count], inplace=True)
    circuit = QuantumCircuit(*compute.qregs, name="constrained_phase")
    circuit.compose(compute, inplace=True)
    # Negative signed difference AND all four constraint flags.
    circuit.h(value[-1])
    circuit.mcx(list(flags), value[-1])
    circuit.h(value[-1])
    circuit.compose(compute.inverse(), inplace=True)
    layout = {"decision": m, "objective": w, "count": c, "comparison_workspace": c-1,
              "constraint_flags": 4, "total": circuit.num_qubits,
              "safe_signed_minimum": problem.lower, "safe_signed_maximum": problem.upper}
    if sum(layout[key] for key in ("decision", "objective", "count", "comparison_workspace", "constraint_flags")) != circuit.num_qubits:
        raise ArithmeticError("Unaccounted quantum workspace")
    return circuit, layout


def complete_iteration(problem, phase=None):
    if problem.m > 8:
        raise ValueError("Generic fixed-weight preparation is restricted to at most eight decisions")
    phase = phase or oracle(problem)[0]
    state = np.zeros(1 << problem.m, dtype=complex)
    import itertools
    for subset in itertools.combinations(range(problem.m), 3):
        state[sum(1 << i for i in subset)] = 1 / math.sqrt(math.comb(problem.m, 3))
    preparation = StatePreparation(state)
    circuit = QuantumCircuit(*phase.qregs, name="one_complete_iteration")
    decision = list(range(problem.m))
    circuit.append(preparation, decision)
    circuit.compose(phase, inplace=True)
    circuit.append(preparation.inverse(), decision)
    circuit.x(decision)
    circuit.h(decision[-1])
    circuit.mcx(decision[:-1], decision[-1])
    circuit.h(decision[-1])
    circuit.x(decision)
    # Convert I-2|0><0| into 2|0><0|-I, keeping the expected global phase explicit.
    circuit.global_phase += math.pi
    circuit.append(preparation, decision)
    return circuit


def synthesize(circuit):
    start = time.perf_counter()
    compiled = transpile(circuit, basis_gates=["u", "cx"], optimization_level=1, seed_transpiler=0)
    gates = {str(k): int(v) for k, v in compiled.count_ops().items()}
    return compiled, {"depth": compiled.depth(), "total_gates": sum(gates.values()),
        "cx_gates": gates.get("cx", 0), "gates": gates,
        "transpile_ms": (time.perf_counter()-start)*1000,
        "coupling": "unconstrained logical connectivity; not a physical-device routing estimate"}


def simulate_small(circuit, problem, expected):
    """Check decision coherences and each workspace marginal without huge snapshots."""
    if problem.m > 5:
        raise ValueError("Native validation simulations are limited to five decisions")
    from qiskit_aer import AerSimulator
    candidate = circuit.copy()
    candidate.save_density_matrix(list(range(problem.m)), label="decision_density")
    for i in range(problem.m, candidate.num_qubits):
        candidate.save_probabilities([i], label=f"workspace_{i}")
    simulator = AerSimulator(method="matrix_product_state", max_parallel_threads=2,
        matrix_product_state_truncation_threshold=0.0, seed_simulator=0)
    compile_start = time.perf_counter()
    candidate = transpile(candidate, simulator, optimization_level=0, seed_transpiler=0)
    validation_transpile_ms = (time.perf_counter()-compile_start)*1000
    start = time.perf_counter()
    result = simulator.run(candidate, shots=1).result()
    if not result.success:
        raise RuntimeError("Native simulator did not complete successfully")
    data = result.data(0)
    density = np.asarray(data["decision_density"], dtype=complex)
    error = float(np.max(np.abs(density - np.outer(expected, expected.conj()))))
    dirty_bound = sum(float(data[f"workspace_{i}"][1]) for i in range(problem.m, candidate.num_qubits))
    norm = float(np.trace(density).real)
    if error > 1e-8 or abs(norm-1) > 1e-8 or dirty_bound > 1e-8:
        raise ArithmeticError(f"Native phase/reflection/workspace mismatch: error={error}, norm={norm}, dirty={dirty_bound}")
    return {"simulation_ms": (time.perf_counter()-start)*1000, "maximum_density_error": error,
            "zero_workspace_probability_lower_bound": max(0., 1-dirty_bound),
            "state_norm": norm, "method": "noiseless MPS, zero configurable truncation threshold",
            "simulated_qubits": circuit.num_qubits, "validation_transpile_ms": validation_transpile_ms}
