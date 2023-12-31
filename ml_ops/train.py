import os

import git
import numpy as np
import pytorch_lightning as pl
import torch

# from mlflow.server import get_app_client
from sklearn.metrics import accuracy_score

from .config import Params, load_cfg
from .data_module import IrisDataModule
from .dataset import IrisData  # , IrisDataset
from .models import SimpleNet
from .serving_utils import export_to_onnx


# from torch.utils.data import DataLoader


class IrisModule(pl.LightningModule):
    def __init__(self, cfg: Params):
        super().__init__()
        self.save_hyperparameters()

        self.cfg = cfg

        self.model = SimpleNet(
            hidden_1=cfg.model.hidden_1_size,
            hidden_2=cfg.model.hidden_2_size,
        )

        self.loss_f = torch.nn.CrossEntropyLoss()
        self.lr = cfg.training.learning_rate  # 5e-2
        self.weight_decay = cfg.training.weight_decay

    def training_step(
        self,
        batch,
        batch_idx,
    ):
        x, y_gt = batch
        y_pr = self.model(x)

        loss = self.loss_f(
            y_pr,
            y_gt.to(torch.long),
        )  # y_gt.float()

        acc = IrisModule.compute_acc(
            y_gt,
            y_pr,
        )  # self.metric(y_pr, y_gt)

        metrics = {
            'loss': loss.detach(),
            'accuracy': acc,
            'mistakes': (1 - acc) * y_gt.shape[0],
        }
        self.log_dict(
            metrics,
            prog_bar=True,
            on_step=True,
            on_epoch=True,
            logger=True,
        )
        # self.train_acc.append(acc.detach())  # optional

        return loss

    @staticmethod
    def compute_acc(y_true: torch.Tensor, pred_probas: torch.Tensor):
        return accuracy_score(
            y_true.detach().numpy(),
            np.argmax(
                pred_probas.detach().numpy(),
                axis=1,
            ),
        )

    def configure_optimizers(self):
        """Define optimizers and LR schedulers."""
        optimizer = torch.optim.SGD(
            self.model.parameters(),
            lr=self.lr,
            weight_decay=self.weight_decay,
        )  # ,
        return optimizer

    def save_model(self, filename):
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        torch.save(
            self.model.state_dict(),
            filename,
        )


def train():
    cfg = load_cfg()

    data = IrisData.load_from_file('data/dataset.npz')

    data_module = IrisDataModule(
        data,
        batch_size=cfg.training.batch_size,
    )
    train_module = IrisModule(
        cfg,
    )

    _logger = pl.loggers.MLFlowLogger(
        experiment_name=cfg.artifacts.experiment_name,
        tracking_uri=cfg.artifacts.log_uri,  # "file:./logs/mlflow_runs",
        # save_dir = "./logs/mlruns"
    )

    try:
        repo = git.Repo(search_parent_directories=True)
        _logger.log_hyperparams({"git_commit_id": repo.head.object.hexsha})
    except git.InvalidGitRepositoryError:
        print("unable to log a git commit id, not a git repository")

    trainer = pl.Trainer(
        accelerator='cpu',
        devices=1,
        max_epochs=cfg.training.epochs,
        logger=_logger,
        log_every_n_steps=cfg.artifacts.checkpoint.every_n_train_steps,
    )

    train_loader = data_module.train_dataloader()

    trainer.fit(
        train_module,
        train_loader,
    )

    # loss_history, acc_history = trainer.train(batch_size=64, epch_num=32)
    train_module.save_model(Params.get_model_save_path(cfg.model))

    export_to_onnx(
        model=train_module.model,
        cfg=cfg,
    )


if __name__ == '__main__':
    train()
