import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import torch
import torch.nn as nn
from flwr.common.parameter import ndarrays_to_parameters
from flwr.server.history import History
from freezegun import freeze_time

from fl4health.checkpointing.checkpointer import BestLossTorchCheckpointer
from fl4health.client_managers.base_sampling_manager import SimpleClientManager
from fl4health.client_managers.poisson_sampling_manager import PoissonSamplingClientManager
from fl4health.parameter_exchange.full_exchanger import FullParameterExchanger
from fl4health.server.base_server import FlServer, FlServerWithCheckpointing
from tests.test_utils.models_for_test import LinearTransform

model = LinearTransform()


class DummyFLServer(FlServer):
    def _hydrate_model_for_checkpointing(self) -> nn.Module:
        return model


def test_no_hydration_with_checkpointer(caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    # Temporary path to write pkl to, will be cleaned up at the end of the test.
    checkpoint_dir = tmp_path.joinpath("resources")
    checkpoint_dir.mkdir()
    checkpointer = BestLossTorchCheckpointer(str(checkpoint_dir), "best_model.pkl")

    # Checkpointer is defined but there is no server-side model hydration to produce a model from the server state.
    # This is not a deal breaker, but may be unintended behavior and the user should be warned
    fl_server_no_hydration = FlServer(PoissonSamplingClientManager(), None, None, checkpointer)
    fl_server_no_hydration._maybe_checkpoint(1.0, {}, server_round=1)
    assert "Server model hydration is not defined" in caplog.text


def test_no_checkpointer_maybe_checkpoint(caplog: pytest.LogCaptureFixture) -> None:
    fl_server_no_checkpointer = FlServer(PoissonSamplingClientManager(), None, None, None)

    # Neither checkpointing nor hydration is defined, we'll have no server-side checkpointing for the FL run.
    fl_server_no_checkpointer._maybe_checkpoint(1.0, {}, server_round=1)
    assert "No checkpointer present. Models will not be checkpointed on server-side." in caplog.text


def test_hydration_and_checkpointer(tmp_path: Path) -> None:
    # Temporary path to write pkl to, will be cleaned up at the end of the test.
    checkpoint_dir = tmp_path.joinpath("resources")
    checkpoint_dir.mkdir()
    checkpointer = BestLossTorchCheckpointer(str(checkpoint_dir), "best_model.pkl")

    # Server-side hydration to convert server state to model and checkpointing behavior are both defined, a model
    # should be saved and be loaded successfully.
    fl_server_both = DummyFLServer(PoissonSamplingClientManager(), None, None, checkpointer)
    fl_server_both._maybe_checkpoint(1.0, {}, server_round=5)
    loaded_model = checkpointer.load_best_checkpoint()
    assert isinstance(loaded_model, LinearTransform)
    # Correct loading tensors of the saved model
    assert torch.equal(model.linear.weight, loaded_model.linear.weight)


def test_fl_server_with_checkpointing(tmp_path: Path) -> None:
    # Temporary path to write pkl to, will be cleaned up at the end of the test.
    checkpoint_dir = tmp_path.joinpath("resources")
    checkpoint_dir.mkdir()
    checkpointer = BestLossTorchCheckpointer(str(checkpoint_dir), "best_model.pkl")
    # Initial model held by server
    initial_model = LinearTransform()
    # represents the model computed by the clients aggregation
    updated_model = LinearTransform()
    parameter_exchanger = FullParameterExchanger()

    server = FlServerWithCheckpointing(
        PoissonSamplingClientManager(), initial_model, parameter_exchanger, None, None, checkpointer
    )
    # Parameters after aggregation (i.e. the updated server-side model)
    server.parameters = ndarrays_to_parameters(parameter_exchanger.push_parameters(updated_model))

    server._maybe_checkpoint(1.0, {}, server_round=5)
    loaded_model = checkpointer.load_best_checkpoint()
    assert isinstance(loaded_model, LinearTransform)
    # Correct loading tensors of the saved model
    assert torch.equal(updated_model.linear.weight, loaded_model.linear.weight)


@patch("fl4health.server.base_server.Server.fit")
@freeze_time("2012-12-12 12:12:12")
def test_metrics_reporter_fit(mock_fit: Mock) -> None:
    test_history = History()
    test_history.metrics_centralized = {"test metrics centralized": [(123, "loss")]}
    test_history.losses_centralized = [(123, 123.123)]
    mock_fit.return_value = test_history

    fl_server = FlServer(SimpleClientManager())
    fl_server.fit(3, None)

    assert fl_server.metrics_reporter.metrics == {
        "type": "server",
        "fit_start": datetime.datetime(2012, 12, 12, 12, 12, 12),
        "fit_end": datetime.datetime(2012, 12, 12, 12, 12, 12),
        "metrics_centralized": test_history.metrics_centralized,
        "losses_centralized": test_history.losses_centralized,
    }


@patch("fl4health.server.base_server.Server.fit_round")
@freeze_time("2012-12-12 12:12:12")
def test_metrics_reporter_fit_round(mock_fit_round: Mock) -> None:
    test_round = 2
    test_metrics_aggregated = "test metrics aggregated"
    mock_fit_round.return_value = (None, test_metrics_aggregated, None)

    fl_server = FlServer(SimpleClientManager())
    fl_server.fit_round(test_round, None)

    assert fl_server.metrics_reporter.metrics == {
        "rounds": {
            test_round: {
                "fit_start": datetime.datetime(2012, 12, 12, 12, 12, 12),
                "metrics_aggregated": test_metrics_aggregated,
                "fit_end": datetime.datetime(2012, 12, 12, 12, 12, 12),
            },
        },
    }


@patch("fl4health.server.base_server.Server.evaluate_round")
@freeze_time("2012-12-12 12:12:12")
def test_metrics_reporter_evaluate_round(mock_evaluate_round: Mock) -> None:
    test_round = 2
    test_loss_aggregated = "test loss aggregated"
    test_metrics_aggregated = "test metrics aggregated"
    mock_evaluate_round.return_value = (test_loss_aggregated, test_metrics_aggregated, (None, None))

    fl_server = FlServer(SimpleClientManager())
    fl_server.evaluate_round(test_round, None)

    assert fl_server.metrics_reporter.metrics == {
        "rounds": {
            test_round: {
                "evaluate_start": datetime.datetime(2012, 12, 12, 12, 12, 12),
                "loss_aggregated": test_loss_aggregated,
                "metrics_aggregated": test_metrics_aggregated,
                "evaluate_end": datetime.datetime(2012, 12, 12, 12, 12, 12),
            },
        },
    }
