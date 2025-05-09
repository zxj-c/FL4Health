import argparse
from logging import INFO
from pathlib import Path
from typing import Tuple

import flwr as fl
import torch
import torch.nn as nn
from flwr.common.logger import log
from flwr.common.typing import Config
from torch.nn.modules.loss import _Loss
from torch.optim import Optimizer
from torch.utils.data import DataLoader

from examples.models.cnn_model import MnistNetWithBnAndFrozen
from fl4health.clients.basic_client import BasicClient
from fl4health.parameter_exchange.layer_exchanger import LayerExchangerWithExclusions
from fl4health.parameter_exchange.parameter_exchanger_base import ParameterExchanger
from fl4health.utils.load_data import load_mnist_data
from fl4health.utils.metrics import Accuracy
from fl4health.utils.sampler import DirichletLabelBasedSampler


class MnistFedBNClient(BasicClient):
    def get_data_loaders(self, config: Config) -> Tuple[DataLoader, DataLoader]:
        batch_size = self.narrow_config_type(config, "batch_size", int)
        sampler = DirichletLabelBasedSampler(list(range(10)), sample_percentage=0.75, beta=1)
        train_loader, val_loader, _ = load_mnist_data(self.data_path, batch_size, sampler)
        return train_loader, val_loader

    def get_optimizer(self, config: Config) -> Optimizer:
        return torch.optim.AdamW(self.model.parameters(), lr=0.01)

    def get_criterion(self, config: Config) -> _Loss:
        return torch.nn.CrossEntropyLoss()

    def get_model(self, config: Config) -> nn.Module:
        return MnistNetWithBnAndFrozen(freeze_cnn_layer=False).to(self.device)

    def get_parameter_exchanger(self, config: Config) -> ParameterExchanger:
        assert self.model is not None
        return LayerExchangerWithExclusions(self.model, {nn.BatchNorm2d})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FL Client Main")
    parser.add_argument("--dataset_path", action="store", type=str, help="Path to the local dataset")
    parser.add_argument(
        "--server_address",
        action="store",
        type=str,
        help="Server Address for the clients to communicate with the server through",
        default="0.0.0.0:8080",
    )
    args = parser.parse_args()

    DEVICE = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    data_path = Path(args.dataset_path)
    log(INFO, f"Device to be used: {DEVICE}")
    log(INFO, f"Server Address: {args.server_address}")

    client = MnistFedBNClient(data_path, [Accuracy()], DEVICE)
    fl.client.start_client(server_address=args.server_address, client=client.to_client())

    # Shutdown the client gracefully
    client.shutdown()
