"""Quantum search service using Grover's Algorithm with Qiskit.

This service implements:
- Grover's Algorithm for quantum search acceleration
- Quantum circuit construction and simulation
- Integration with classical vector similarity search
- Quantum-enhanced document retrieval
"""

import math
import logging
import re
from typing import List, Dict, Any
import numpy as np

# Qiskit for quantum computing
from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister
from qiskit import transpile
from qiskit_aer import AerSimulator
from qiskit.circuit.library import ZGate

# Configuration
from config import settings

logger = logging.getLogger(__name__)

class QuantumSearch:
    """Quantum search service using Grover's Algorithm for enhanced vector search."""
    
    def __init__(self):
        """Initialize quantum search service."""
        self.simulator = AerSimulator()
        self.max_qubits = settings.QUANTUM_MAX_QUBITS
        self.quantum_shots = settings.QUANTUM_SHOTS
        
        logger.info(f"QuantumSearch initialized with max {self.max_qubits} qubits")
    
    def _calculate_similarity_scores(
        self, 
        query_embedding: List[float], 
        document_embeddings: List[List[float]]
    ) -> List[float]:
        """Calculate cosine similarity scores between query and documents.
        
        Args:
            query_embedding: Query embedding vector
            document_embeddings: List of document embedding vectors
            
        Returns:
            List[float]: Similarity scores for each document
        """
        try:
            query_array = np.array(query_embedding)
            similarities = []
            
            for doc_embedding in document_embeddings:
                doc_array = np.array(doc_embedding)
                
                # Calculate cosine similarity
                dot_product = np.dot(query_array, doc_array)
                query_norm = np.linalg.norm(query_array)
                doc_norm = np.linalg.norm(doc_array)
                
                if query_norm == 0 or doc_norm == 0:
                    similarity = 0.0
                else:
                    similarity = dot_product / (query_norm * doc_norm)
                
                similarities.append(max(0.0, similarity))  # Ensure non-negative
            
            return similarities
            
        except Exception as e:
            logger.error(f"Failed to calculate similarity scores: {e}")
            return [0.0] * len(document_embeddings)

    def _is_low_information_document(self, text: str) -> bool:
        """Return True for structural/marker chunks that should not drive answers."""
        if not text:
            return True

        normalized = text.strip()
        if not normalized:
            return True

        # Page separators like "--- Page 1 ---" are useful structure, not answer context.
        if re.fullmatch(r"-+\s*page\s*\d+\s*-+", normalized, flags=re.IGNORECASE):
            return True

        # If almost no alphanumeric signal exists, treat as noise.
        alpha_num_count = sum(1 for ch in normalized if ch.isalnum())
        if alpha_num_count < 20:
            return True

        return False

    def _prioritize_informative_results(self, ranked_items: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
        """Prefer informative chunks and only backfill with low-info chunks if needed."""
        informative_items = []
        low_information_items = []

        for item in ranked_items:
            doc_text = item.get("document", {}).get("document", "")
            if self._is_low_information_document(doc_text):
                low_information_items.append(item)
            else:
                informative_items.append(item)

        if informative_items:
            selected = informative_items[:top_k]
            if len(selected) < top_k:
                selected.extend(low_information_items[: top_k - len(selected)])
            return selected

        # If every chunk is low-information, preserve previous behavior.
        return ranked_items[:top_k]
    
    def _create_oracle(self, marked_items: List[int], num_qubits: int) -> QuantumCircuit:
        """Create oracle circuit that marks target items.
        
        Args:
            marked_items: Indices of items to mark (high similarity)
            num_qubits: Number of qubits in the circuit
            
        Returns:
            QuantumCircuit: Oracle circuit
        """
        oracle = QuantumCircuit(num_qubits)
        
        # Mark each target item by flipping its phase
        for item in marked_items:
            # Convert item index to binary representation
            binary_repr = format(item, f'0{num_qubits}b')
            
            # Apply X gates to qubits that should be 0 in the target state
            for i, bit in enumerate(binary_repr):
                if bit == '0':
                    oracle.x(i)
            
            # Apply multi-controlled Z gate
            if num_qubits == 1:
                oracle.z(0)
            else:
                mcz_gate = ZGate().control(num_qubits - 1)
                oracle.append(mcz_gate, list(range(num_qubits)))
            
            # Undo X gates
            for i, bit in enumerate(binary_repr):
                if bit == '0':
                    oracle.x(i)
        
        return oracle
    
    def _create_diffuser(self, num_qubits: int) -> QuantumCircuit:
        """Create diffuser circuit for amplitude amplification.
        
        Args:
            num_qubits: Number of qubits in the circuit
            
        Returns:
            QuantumCircuit: Diffuser circuit
        """
        diffuser = QuantumCircuit(num_qubits)
        
        # Apply Hadamard gates
        diffuser.h(range(num_qubits))
        
        # Apply X gates
        diffuser.x(range(num_qubits))
        
        # Apply multi-controlled Z gate
        if num_qubits == 1:
            diffuser.z(0)
        else:
            mcz_gate = ZGate().control(num_qubits - 1)
            diffuser.append(mcz_gate, list(range(num_qubits)))
        
        # Undo X gates
        diffuser.x(range(num_qubits))
        
        # Undo Hadamard gates
        diffuser.h(range(num_qubits))
        
        return diffuser
    
    def _run_grovers_algorithm(
        self, 
        num_items: int, 
        marked_items: List[int]
    ) -> Dict[int, float]:
        """Run Grover's Algorithm to find marked items.
        
        Args:
            num_items: Total number of items to search
            marked_items: Indices of items to find
            
        Returns:
            Dict[int, float]: Probability distribution over items
        """
        try:
            # Calculate number of qubits needed
            num_qubits = math.ceil(math.log2(max(num_items, 2)))
            
            # Limit qubits to prevent excessive computation
            if num_qubits > self.max_qubits:
                logger.warning(f"Too many qubits needed ({num_qubits}), limiting to {self.max_qubits}")
                num_qubits = self.max_qubits
                num_items = min(num_items, 2**num_qubits)
            
            # Calculate optimal number of iterations
            if len(marked_items) == 0:
                return {}
            
            optimal_iterations = math.floor(
                math.pi / 4 * math.sqrt(num_items / len(marked_items))
            )
            optimal_iterations = max(1, min(optimal_iterations, 10))  # Limit iterations
            
            logger.info(f"Running Grover's with {num_qubits} qubits, {optimal_iterations} iterations")
            
            # Create quantum circuit
            qreg = QuantumRegister(num_qubits, 'q')
            creg = ClassicalRegister(num_qubits, 'c')
            circuit = QuantumCircuit(qreg, creg)
            
            # Initialize superposition
            circuit.h(range(num_qubits))
            
            # Create oracle and diffuser
            oracle = self._create_oracle(marked_items, num_qubits)
            diffuser = self._create_diffuser(num_qubits)
            
            # Apply Grover iterations
            for _ in range(optimal_iterations):
                circuit.compose(oracle, inplace=True)
                circuit.compose(diffuser, inplace=True)
            
            # Measure
            circuit.measure(range(num_qubits), range(num_qubits))
            
            # Execute circuit
            transpiled_circuit = transpile(circuit, self.simulator)
            job = self.simulator.run(transpiled_circuit, shots=self.quantum_shots)
            result = job.result()
            counts = result.get_counts()
            
            # Convert counts to probabilities
            probabilities = {}
            for bitstring, count in counts.items():
                index = int(bitstring, 2)
                if index < num_items:  # Only consider valid indices
                    probabilities[index] = count / self.quantum_shots
            
            return probabilities
            
        except Exception as e:
            logger.error(f"Grover's algorithm execution failed: {e}")
            return {}
    
    async def quantum_enhanced_search(
        self,
        query_embedding: List[float],
        document_embeddings: List[Dict[str, Any]],
        similarity_threshold: float = 0.7,
        top_k: int = 5
    ) -> Dict[str, Any]:
        """Perform quantum-enhanced similarity search.
        
        Args:
            query_embedding: Query embedding vector
            document_embeddings: List of documents with embeddings
            similarity_threshold: Minimum similarity for quantum marking
            top_k: Number of top results to return
            
        Returns:
            Dict with ranked results and the actual search method used
        """
        try:
            logger.info(f"Starting quantum-enhanced search for {len(document_embeddings)} documents")
            
            if not document_embeddings:
                return {"results": [], "search_method": "none"}
            
            # Extract embeddings for similarity calculation
            embeddings = [doc["embedding"] for doc in document_embeddings]
            
            # Calculate classical similarity scores
            similarity_scores = self._calculate_similarity_scores(
                query_embedding, embeddings
            )
            
            # Find items above similarity threshold for quantum marking
            marked_items = [
                i for i, score in enumerate(similarity_scores)
                if score >= similarity_threshold
            ]
            
            logger.info(f"Found {len(marked_items)} documents above threshold {similarity_threshold}")
            
            # If no items above threshold, fall back to classical top-k
            if not marked_items:
                logger.info("No items above threshold, using classical search")
                fallback = await self._classical_top_k_search(
                    document_embeddings, similarity_scores, top_k, search_method="classical_fallback"
                )
                return {
                    "results": fallback,
                    "search_method": "classical_fallback",
                    "fallback_reason": "no_marked_items",
                }
            
            # If too many items, limit to prevent quantum overhead
            if len(document_embeddings) > 2**self.max_qubits:
                logger.info("Too many documents for quantum search, using classical approach")
                fallback = await self._classical_top_k_search(
                    document_embeddings, similarity_scores, top_k, search_method="classical_fallback"
                )
                return {
                    "results": fallback,
                    "search_method": "classical_fallback",
                    "fallback_reason": "too_many_documents",
                }
            
            # Run Grover's Algorithm
            quantum_probabilities = self._run_grovers_algorithm(
                len(document_embeddings), marked_items
            )

            if not quantum_probabilities:
                logger.info("Grover probabilities were empty, using classical fallback")
                fallback = await self._classical_top_k_search(
                    document_embeddings, similarity_scores, top_k, search_method="classical_fallback"
                )
                return {
                    "results": fallback,
                    "search_method": "classical_fallback",
                    "fallback_reason": "empty_quantum_probabilities",
                }
            
            # Combine quantum probabilities with classical similarities
            enhanced_scores = []
            for i, doc in enumerate(document_embeddings):
                classical_score = similarity_scores[i]
                quantum_boost = quantum_probabilities.get(i, 0.0)
                
                # Combine scores (quantum boost amplifies high-similarity items)
                enhanced_score = classical_score * (1 + quantum_boost * settings.QUANTUM_BOOST_FACTOR)
                
                enhanced_scores.append({
                    "index": i,
                    "document": doc,
                    "classical_similarity": classical_score,
                    "quantum_probability": quantum_boost,
                    "enhanced_score": enhanced_score
                })
            
            # Sort by enhanced score
            enhanced_scores.sort(key=lambda x: x["enhanced_score"], reverse=True)
            top_results = self._prioritize_informative_results(enhanced_scores, top_k)
            
            # Format results
            formatted_results = []
            for result in top_results:
                formatted_result = {
                    "id": result["document"]["id"],
                    "document": result["document"]["document"],
                    "metadata": result["document"]["metadata"],
                    "classical_similarity": result["classical_similarity"],
                    "similarity_score": result["enhanced_score"],
                    "quantum_probability": result["quantum_probability"],
                    "enhanced_score": result["enhanced_score"],
                    "search_method": "quantum_enhanced"
                }
                formatted_results.append(formatted_result)
            
            logger.info(f"Quantum-enhanced search ranked {len(formatted_results)} results")
            return {"results": formatted_results, "search_method": "quantum_enhanced"}
            
        except Exception as e:
            logger.error(f"Quantum-enhanced search failed: {e}")
            # Fall back to classical search
            fallback = await self._classical_top_k_search(
                document_embeddings, 
                self._calculate_similarity_scores(query_embedding, [doc["embedding"] for doc in document_embeddings]),
                top_k,
                search_method="classical_fallback",
            )
            return {
                "results": fallback,
                "search_method": "classical_fallback",
                "fallback_reason": "quantum_exception",
            }

    async def classical_similarity_search(
        self,
        query_embedding: List[float],
        document_embeddings: List[Dict[str, Any]],
        top_k: int = 5,
        search_method: str = "classical",
    ) -> Dict[str, Any]:
        """Perform pure classical ranking over the provided candidate vectors."""
        if not document_embeddings:
            return {"results": [], "search_method": "none"}

        similarity_scores = self._calculate_similarity_scores(
            query_embedding,
            [doc["embedding"] for doc in document_embeddings],
        )
        results = await self._classical_top_k_search(
            document_embeddings,
            similarity_scores,
            top_k,
            search_method=search_method,
        )
        return {"results": results, "search_method": search_method}
    
    async def _classical_top_k_search(
        self,
        document_embeddings: List[Dict[str, Any]],
        similarity_scores: List[float],
        top_k: int,
        search_method: str = "classical",
    ) -> List[Dict[str, Any]]:
        """Fallback classical top-k similarity search.
        
        Args:
            document_embeddings: List of documents with embeddings
            similarity_scores: Precomputed similarity scores
            top_k: Number of top results to return
            
        Returns:
            List[Dict]: Classical search results
        """
        try:
            # Combine documents with scores
            scored_docs = [
                {
                    "index": i,
                    "document": doc,
                    "similarity_score": score
                }
                for i, (doc, score) in enumerate(zip(document_embeddings, similarity_scores))
            ]
            
            # Sort by similarity score
            scored_docs.sort(key=lambda x: x["similarity_score"], reverse=True)
            top_results = self._prioritize_informative_results(scored_docs, top_k)
            
            # Format results
            formatted_results = []
            for result in top_results:
                formatted_result = {
                    "id": result["document"]["id"],
                    "document": result["document"]["document"],
                    "metadata": result["document"]["metadata"],
                    "similarity_score": result["similarity_score"],
                    "search_method": search_method
                }
                formatted_results.append(formatted_result)
            
            return formatted_results
            
        except Exception as e:
            logger.error(f"Classical search failed: {e}")
            return []
    
    async def get_quantum_stats(self) -> Dict[str, Any]:
        """Get quantum search service statistics.
        
        Returns:
            Dict: Service statistics and capabilities
        """
        return {
            "service": "quantum_search",
            "algorithm": "grovers",
            "max_qubits": self.max_qubits,
            "quantum_shots": self.quantum_shots,
            "max_searchable_items": 2**self.max_qubits,
            "simulator": "qiskit_aer",
            "boost_factor": settings.QUANTUM_BOOST_FACTOR,
            "status": "ready"
        }
