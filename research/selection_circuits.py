"""Small Qiskit reference circuits for the compact selector's unit tests.

Generic StatePreparation is deliberately limited to small reference instances;
it is not presented as a scalable Dicke-state circuit or the 15-candidate engine.
The main selector executes the equivalent ideal feasible-subspace simulation.
"""
from __future__ import annotations

import math
import numpy as np

from .selection import SelectionProblem, _integer, subset_layout


def reference_circuit(problem: SelectionProblem, threshold: int, iterations: int,
                      max_qubits: int = 20):
    from qiskit import QuantumCircuit
    from qiskit.circuit.library import QuadraticForm, StatePreparation

    _integer("iterations", iterations)
    _integer("max_qubits", max_qubits, 1)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, np.integer)):
        raise ValueError("Threshold must be an integer energy")
    n, k = len(problem.features.ids), problem.count
    if n == 0 or n > 10:
        raise ValueError("Reference circuits support 1 to 10 candidates only")
    resource = problem.resources()
    if not resource["energy_lower_bound"] <= threshold <= resource["energy_upper_bound"]:
        raise ValueError("Threshold outside the safe feasible-energy interval")
    width = resource["value_qubits"]
    if n + width > max_qubits:
        raise ValueError("Reference circuit exceeds max_qubits")
    layout = subset_layout(n, k)
    amplitudes = np.zeros(1 << n, dtype=np.complex128)
    for subset in layout:
        address = sum(1 << int(i) for i in subset)
        amplitudes[address] = 1 / math.sqrt(len(layout))
    preparation = StatePreparation(amplitudes)
    # QuadraticForm adds A_ij + A_ji; encode each pair once.
    oracle_value = QuadraticForm(width, np.triu(problem.quadratic, 1).tolist(),
                                 (-problem.linear).tolist(), -int(threshold), little_endian=True)
    circuit = QuantumCircuit(n + width)
    circuit.append(preparation, range(n))
    for _ in range(iterations):
        circuit.compose(oracle_value, inplace=True)
        circuit.z(n + width - 1)
        circuit.compose(oracle_value.inverse(), inplace=True)
        circuit.append(preparation.inverse(), range(n))
        circuit.x(range(n))
        if n == 1:
            circuit.z(0)
        else:
            circuit.h(n - 1)
            circuit.mcx(list(range(n - 1)), n - 1)
            circuit.h(n - 1)
        circuit.x(range(n))
        circuit.append(preparation, range(n))
    return circuit
