import argparse
import os
from logging import INFO
from pathlib import Path
from typing import Optional, Sequence, Tuple

import flwr as fl
import torch
import torch.nn as nn
from flamby.datasets.fed_heart_disease import BATCH_SIZE, LR, NUM_CLIENTS, BaselineLoss
from flwr.common.logger import log
from flwr.common.typing import Config
from torch.nn.modules.loss import _Loss
from torch.optim import Optimizer
from torch.utils.data import DataLoader

from fl4health.checkpointing.checkpointer import BestLossTorchCheckpointer, LatestTorchCheckpointer
from fl4health.checkpointing.client_module import ClientCheckpointModule
from fl4health.clients.fenda_client import FendaClient
from fl4health.utils.losses import LossMeterType
from fl4health.utils.metrics import Accuracy, Metric
from fl4health.utils.random import set_all_random_seeds
from research.flamby.fed_heart_disease.perfcl.perfcl_model import FedHeartDiseasePerFclModel
from research.flamby.flamby_data_utils import construct_fed_heard_disease_train_val_datasets


class FedHeartDiseasePerFclClient(FendaClient):
    def __init__(
        self,
        data_path: Path,
        metrics: Sequence[Metric],
        device: torch.device,
        client_number: int,
        learning_rate: float,
        loss_meter_type: LossMeterType = LossMeterType.AVERAGE,
        checkpointer: Optional[ClientCheckpointModule] = None,
        extra_loss_weights: Tuple[float, float] = (10, 10),
    ) -> None:
        super().__init__(
            data_path=data_path,
            metrics=metrics,
            device=device,
            loss_meter_type=loss_meter_type,
            checkpointer=checkpointer,
        )
        self.client_number = client_number
        self.learning_rate: float = learning_rate

        self.perfcl_loss_weights = extra_loss_weights

        assert 0 <= client_number < NUM_CLIENTS
        log(INFO, f"Client Name: {self.client_name}, Client Number: {self.client_number}")

    def get_data_loaders(self, config: Config) -> Tuple[DataLoader, DataLoader]:
        train_dataset, validation_dataset = construct_fed_heard_disease_train_val_datasets(
            self.client_number, str(self.data_path)
        )
        train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True)
        val_loader = DataLoader(validation_dataset, batch_size=BATCH_SIZE, shuffle=False)
        return train_loader, val_loader

    def get_model(self, config: Config) -> nn.Module:
        model: nn.Module = FedHeartDiseasePerFclModel().to(self.device)
        return model

    def get_optimizer(self, config: Config) -> Optimizer:
        return torch.optim.AdamW(self.model.parameters(), lr=self.learning_rate)

    def get_criterion(self, config: Config) -> _Loss:
        return BaselineLoss()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FL Client Main")
    parser.add_argument(
        "--artifact_dir",
        action="store",
        type=str,
        help="Path to save client artifacts such as logs and model checkpoints",
        required=True,
    )
    parser.add_argument(
        "--dataset_dir",
        action="store",
        type=str,
        help="Path to the preprocessed Fed Heart Disease Dataset (ex. path/to/fed_heart_disease)",
        required=True,
    )
    parser.add_argument(
        "--run_name",
        action="store",
        help="Name of the run, model checkpoints will be saved under a subfolder with this name",
        required=True,
    )
    parser.add_argument(
        "--server_address",
        action="store",
        type=str,
        help="Server Address for the clients to communicate with the server through",
        default="0.0.0.0:8080",
    )
    parser.add_argument(
        "--client_number",
        action="store",
        type=int,
        help="Number of the client for dataset loading (should be 0-3 for Fed Heart Disease)",
        required=True,
    )
    parser.add_argument(
        "--learning_rate", action="store", type=float, help="Learning rate for local optimization", default=LR
    )
    parser.add_argument(
        "--seed",
        action="store",
        type=int,
        help="Seed for the random number generators across python, torch, and numpy",
        required=False,
    )
    parser.add_argument(
        "--mu",
        action="store",
        type=float,
        help="Weights for the Perfcl loss mentioned in paper",
        required=False,
    )
    parser.add_argument(
        "--gamma",
        action="store",
        type=float,
        help="Weights for the Perfcl loss mentioned in paper",
        required=False,
    )
    parser.add_argument(
        "--no_federated_checkpointing",
        action="store_true",
        help="boolean to disable client-side federated checkpointing in the personal FL experiment",
    )
    args = parser.parse_args()

    DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    log(INFO, f"Device to be used: {DEVICE}")
    log(INFO, f"Server Address: {args.server_address}")
    log(INFO, f"Learning Rate: {args.learning_rate}")
    log(INFO, f"Performing Federated Checkpointing: {not args.no_federated_checkpointing}")

    # Set the random seed for reproducibility
    set_all_random_seeds(args.seed)

    federated_checkpointing = not args.no_federated_checkpointing
    checkpoint_dir = os.path.join(args.artifact_dir, args.run_name)
    checkpoint_name = f"client_{args.client_number}_best_model.pkl"
    post_aggregation_checkpointer = (
        BestLossTorchCheckpointer(checkpoint_dir, checkpoint_name)
        if federated_checkpointing
        else LatestTorchCheckpointer(checkpoint_dir, checkpoint_name)
    )
    checkpointer = ClientCheckpointModule(post_aggregation=post_aggregation_checkpointer)

    client = FedHeartDiseasePerFclClient(
        data_path=Path(args.dataset_dir),
        metrics=[Accuracy("FedHeartDisease_accuracy")],
        device=DEVICE,
        client_number=args.client_number,
        learning_rate=args.learning_rate,
        checkpointer=checkpointer,
        extra_loss_weights=(args.mu, args.gamma),
    )

    fl.client.start_client(
        server_address=args.server_address,
        client=client.to_client(),
    )

    # Shutdown the client gracefully
    client.shutdown()
