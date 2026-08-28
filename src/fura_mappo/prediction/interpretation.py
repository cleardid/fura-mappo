"""WP-03B Primary ID prediction-science interpretation rule。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from fura_mappo.prediction.bootstrap import PairedTraceBootstrapResult


class PrimaryIDLabel(str, Enum):
    """Primary ID learned-vs-B* 的冻结解释标签。"""

    LEARNED_BETTER = "LEARNED_BETTER"
    LEARNED_WORSE = "LEARNED_WORSE"
    NO_CLEAR_DIFFERENCE = "NO_CLEAR_DIFFERENCE"


def _interpret_primary_id(
    delta_rmse: float,
    ci_lower: float,
    ci_upper: float,
) -> PrimaryIDLabel:
    """应用 Primary ID 冻结的严格符号规则。"""

    if delta_rmse < 0.0 and ci_upper < 0.0:
        return PrimaryIDLabel.LEARNED_BETTER
    if delta_rmse > 0.0 and ci_lower > 0.0:
        return PrimaryIDLabel.LEARNED_WORSE
    return PrimaryIDLabel.NO_CLEAR_DIFFERENCE


@dataclass(frozen=True, slots=True, eq=False)
class PrimaryIDInterpretation:
    """解释一个上游已确定为 Primary ID 的配对 bootstrap 数学结果。

    该 label 只解释 Primary ID prediction-error comparison。该对象不能自行证明实际
    test_id、manifest、source、test-exposure、bootstrap spec 或 runtime provenance，也不是
    Formal H1 verdict、forecast-control/Oracle/MAPPO gate 或 deployment decision。
    """

    bootstrap_result: PairedTraceBootstrapResult
    label: PrimaryIDLabel = field(init=False)

    def __post_init__(self) -> None:
        """验证上游结果并派生唯一解释标签。"""

        if not isinstance(self.bootstrap_result, PairedTraceBootstrapResult):
            raise TypeError(
                "bootstrap_result must be a PairedTraceBootstrapResult, got "
                f"{type(self.bootstrap_result).__name__}"
            )

        delta_rmse = self.bootstrap_result.point_delta_rmse
        ci_lower = self.bootstrap_result.ci_lower
        ci_upper = self.bootstrap_result.ci_upper

        if not all(math.isfinite(value) for value in (delta_rmse, ci_lower, ci_upper)):
            raise ValueError("delta_rmse and confidence interval endpoints must be finite")
        if ci_lower > ci_upper:
            raise ValueError("ci_lower must be less than or equal to ci_upper")

        object.__setattr__(
            self,
            "label",
            _interpret_primary_id(delta_rmse, ci_lower, ci_upper),
        )

    @property
    def delta_rmse(self) -> float:
        """返回上游 locked-test 点估计的 learned-minus-B* RMSE。"""

        return self.bootstrap_result.point_delta_rmse

    @property
    def ci_lower(self) -> float:
        """返回上游配对 bootstrap 置信区间下端点。"""

        return self.bootstrap_result.ci_lower

    @property
    def ci_upper(self) -> float:
        """返回上游配对 bootstrap 置信区间上端点。"""

        return self.bootstrap_result.ci_upper


def interpret_primary_id_bootstrap(
    bootstrap_result: PairedTraceBootstrapResult,
) -> PrimaryIDInterpretation:
    """将上游 Primary ID bootstrap 结果解释为冻结科学标签。"""

    if not isinstance(bootstrap_result, PairedTraceBootstrapResult):
        raise TypeError(
            "bootstrap_result must be a PairedTraceBootstrapResult, got "
            f"{type(bootstrap_result).__name__}"
        )
    return PrimaryIDInterpretation(bootstrap_result=bootstrap_result)


__all__ = [
    "PrimaryIDInterpretation",
    "PrimaryIDLabel",
    "interpret_primary_id_bootstrap",
]
