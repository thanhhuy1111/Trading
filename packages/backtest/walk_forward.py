from datetime import datetime, timedelta
from typing import List
from uuid import UUID, uuid4

from packages.backtest.models import WalkForwardFold


class WalkForwardRunner:
    """Generates train/validation/test folds with purging and embargo isolation."""

    def generate_folds(
        self,
        session_id: UUID,
        start_time: datetime,
        end_time: datetime,
        num_folds: int = 3,
        purge_hours: int = 24,
        embargo_hours: int = 24
    ) -> List[WalkForwardFold]:

        if end_time <= start_time:
            raise ValueError("WALK_FORWARD_ERROR: End time must be after start time")

        total_duration = end_time - start_time
        fold_duration = total_duration / num_folds
        folds: List[WalkForwardFold] = []

        purge_delta = timedelta(hours=purge_hours)
        embargo_delta = timedelta(hours=embargo_hours)

        for i in range(num_folds):
            f_start = start_time + (fold_duration * i)
            f_end = start_time + (fold_duration * (i + 1))

            # Train: 60%, Validation: 20%, Test: 20%
            f_len = f_end - f_start
            train_end = f_start + (f_len * 0.6) - purge_delta
            val_start = train_end + purge_delta + embargo_delta
            val_end = f_start + (f_len * 0.8) - purge_delta
            test_start = val_end + purge_delta + embargo_delta
            test_end = f_end

            fold = WalkForwardFold(
                fold_id=uuid4(),
                session_id=session_id,
                fold_number=i + 1,
                train_start=f_start,
                train_end=train_end,
                validation_start=val_start,
                validation_end=val_end,
                test_start=test_start,
                test_end=test_end
            )
            folds.append(fold)

        return folds


walk_forward_runner = WalkForwardRunner()
