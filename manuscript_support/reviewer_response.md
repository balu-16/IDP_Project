# Response to technical comments — ICECMSN-1883

Manuscript: **Qubit Chat: A Controlled Evaluation of Grover-Inspired Reranking for Document Retrieval**.

The revision uses complete verified test runs, without collecting new dataset rankings during manuscript preparation. The uniform method name does not imply identical configurations. Newer official tests are explicitly follow-up evaluations. NFCorpus's failed confirmation recall gate and subsequent unchanged-parameter continuation are disclosed in the protocol.

## Technical comments 1.1: only two datasets

The evidence now includes all 300 SciFact, 323 NFCorpus, and 648 FiQA test queries, including FiQA's 57,638 parents. SciFact and NFCorpus include protected-prefix refinement; FiQA reports the earlier fifteen-candidate configuration. Matched optimizers use the corresponding configuration; these are distinct policies within the L6-guided GAS family. The 100-query FiQA confirmation is excluded. Table II, p. 4

## Technical comments 1.2: classical cosine dependence

The manuscript explicitly charges and describes classical dense/BM25 retrieval, neural relevance scoring, and final ordering. Grover is used for joint subset search, with classical exact/greedy controls and no claim of quantum corpus search. Section IV, p. 3

## Technical comments 1.3: high P95 simulation latency

Complete online P50/P95 includes original/additional inference, both selection stages, and upstream retrieval wherever used. Combined selector and refinement-only boundaries are separate. Expanded scoring increases latency versus matched base selection; matched classical methods are reported without a Grover speed claim. Table V, p. 6; Table VI, p. 6

## Technical comments 1.4: incomplete hardware

Added Intel Core i7-1355U, 12 logical CPUs, approximately 15.3 GiB RAM, two compute threads, OS/Python/library versions, warm-up/loading boundaries, shared-host limitations, and full hardware/session records in the companion evidence. Section III, p. 2

## Technical comments 1.5: advanced neural comparisons

Added pinned MS MARCO MiniLM L2/L6 cross-encoders on dense-fifteen and dense-sixty-four pools, along with hybrid-fifteen L6-only. The different pools are disclosed. These are specific neural controls, not an exhaustive state-of-the-art survey. Table III, p. 5

## Technical comments 1.6: figure citations/numbering

The pipeline diagram is explicitly cited before its appearance and uses consistent classical/base/refinement labels. Figures and tables use LaTeX cross-references and compiled sequential numbering. Fig. 1, p. 3

## Technical comments 1.7: conclusion length

The conclusion is one generated paragraph containing 172 whitespace-delimited words (150–200 required). Section VII, p. 7

## Technical comments 2.1: alternative thresholds and no-marked fallback

The already recorded development comparison at cosine thresholds 0.3/0.5/0.7 is summarized with no-marked rates computed from saved candidates. The frozen winner is retained; no rankings or thresholds were retuned on test judgments. Adaptive subset-energy marking replaces the static relevance threshold and preserves a feasible incumbent. Table VII, p. 7

## Technical comments 2.2: score transformation and relevance order

The mechanism was redesigned rather than claiming an optimized probability-to-relevance formula. Marked states have symmetric ideal amplification; probabilities do not inherently provide graded relevance. Raw L6 determines base ordering and tail order, while the protected prefix deliberately takes priority over global sorting. Cosine remains upstream retrieval and redundancy evidence. The original probability-based policy remains a comparator. Section IV, p. 3

## Technical comments 2.3: candidate/precision circuit resources — PARTIALLY ADDRESSED

Added observed candidate/basis sizes and simulation time, analytical amplitude-storage and signed-register scaling, explicit objective enumeration, phase/compute-uncompute accounting, and quantization proofs. A full native constrained-oracle circuit-depth/precision sweep has not been performed. The paper labels this outstanding and does not reuse incompatible legacy depths as new-method measurements. Table VIII, p. 7; Table IX, p. 7

## Technical comments 2.4: additional classical rerankers

Included RRF, independently development-tuned MMR, L6-only, greedy, exact float/integer, and random-search controls. The aggregate-quality agreement of matched protected controls on SciFact and NFCorpus is reported explicitly. No uniquely quantum effectiveness gain is asserted. Table III, p. 5

## Technical comments 2.5: larger document collection

The full 648-query FiQA L6-guided GAS test covers 57,638 parents, versus 5,183 SciFact and 3,633 NFCorpus parents. This extends domain/classical-corpus coverage, without demonstrating quantum corpus-size scaling. A full FiQA refinement test remains unavailable in this revision. Table I, p. 2

## Evidence and remaining author actions

`records/evidence.json` and `records/provenance.json` bind values to sealed inputs; `records/all_methods.csv` retains all controls. Statistical reports preserve numerical ties and complete correction families. The supplied IEEEtran class is unchanged; the final PDF is checked for page count, fonts, references, and overflow.

The unperformed native constrained-oracle depth study remains an explicit limitation. The full FiQA refinement test is not included yet. Local checks do not replace organizer/PDF eXpress acceptance. Nothing has been submitted.
