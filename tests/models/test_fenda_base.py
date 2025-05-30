from fl4health.model_bases.fenda_base import FendaModel
from tests.test_utils.models_for_test import FeatureCnn, FendaHeadCnn


def test_fenda_model_gets_correct_layers() -> None:
    model = FendaModel(FeatureCnn(), FeatureCnn(), FendaHeadCnn())
    layers_to_exchange = model.layers_to_exchange()
    filtered_layer_names = [
        layer_name for layer_name in model.state_dict().keys() if layer_name.startswith("global_module.")
    ]
    for test_layer, expected_layer in zip(layers_to_exchange, filtered_layer_names):
        assert test_layer == expected_layer
