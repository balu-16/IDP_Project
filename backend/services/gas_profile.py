"""Application settings kept separate from the frozen benchmark configuration."""
from dataclasses import dataclass

from .gas_selector.baseline import Config as BaselineConfig
from .gas_selector.refinement import Config as RefinementConfig

L6_MODEL = 'cross-encoder/ms-marco-MiniLM-L6-v2'
L6_REVISION = '233902d25c440f23af6f7d6e94d2946bac0bee0a'


@dataclass(frozen=True)
class ApplicationGASProfile:
    dense_count: int = 64
    shortlist_count: int = 15
    selected_count: int = 8
    protected_prefix: int = 5
    lexical_weight: float = 0.25
    diversity_weight: float = 0.05
    phase_calls: int = 64
    trials: int = 32
    growth: float = 1.2
    time_limit_seconds: float = 15.0
    max_subsets: int = 200_000

    def baseline(self):
        return BaselineConfig(lexical_weight=self.lexical_weight,
            diversity_weight=self.diversity_weight, candidate_limit=self.shortlist_count,
            selected_count=self.selected_count, coefficient_bits=8,
            max_oracle_calls=self.phase_calls, max_trials=self.trials,
            window_growth=self.growth, time_limit_seconds=self.time_limit_seconds,
            max_subsets=self.max_subsets)

    def refinement(self):
        return RefinementConfig(protected_prefix=self.protected_prefix,
            selected_count=self.selected_count, coefficient_bits=16,
            max_oracle_calls=self.phase_calls, max_trials=self.trials,
            window_growth=self.growth, time_limit_seconds=self.time_limit_seconds,
            max_subsets=self.max_subsets)


APPLICATION_GAS = ApplicationGASProfile()
