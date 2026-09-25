from __future__ import annotations

import os
import pickle
from functools import partial
from typing import Optional

import torch
from torch.utils.data import DataLoader

from Funsearch.Evaluator.eval_utils import load_rcc8_file_as_dict, set_seed
from Funsearch.Evaluator.model import EdgeTransformer
from Funsearch.Evaluator.train import batch_edges_multi, collate, parse_args


def train_edge_transformer(
    *,
    train_csv_path: str,
    model_output_path: str,
    unique_labels_path: Optional[str] = None,
    dataset_type: str = "no_ambiguity_v2",
    epochs: int = 100,
    batch_size: int = 32,
    lr: float = 1e-3,
    seed: int = 42,
    log_dir: Optional[str] = None,
    val_check_interval: int = 10,
    logger=None,
) -> tuple[str, float]:
    """Train an EdgeTransformer from a CSV and save the state-dict.

    Mirrors `Funsearch/MultiRoundEvalTrainer/helpers.py::train_edge_transformer`.
    Returns `(model_output_path, best_val_acc)`.
    """
    import lightning.pytorch as pl

    if unique_labels_path is None:
        unique_labels_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "..",
            "Funsearch",
            "Evaluator",
            "unique_labels.pkl",
        )
        unique_labels_path = os.path.abspath(unique_labels_path)

    set_seed(seed)

    with open(unique_labels_path, "rb") as f:
        unique_edge_labels, unique_query_labels = pickle.load(f)

    pkl_cache = train_csv_path + ".pkl"
    if os.path.exists(pkl_cache):
        os.remove(pkl_cache)
        if logger:
            logger.info(f"Removed stale cache: {pkl_cache}")

    cl_args = parse_args([])
    cl_args.dataset_type = dataset_type
    cl_args.epochs = epochs
    cl_args.batch_size = batch_size
    cl_args.lr = lr
    cl_args.seed = seed

    if logger:
        logger.info(f"Loading training data from {train_csv_path}")

    data = load_rcc8_file_as_dict(train_csv_path)
    from Funsearch.Evaluator.eval_utils import ClutrrDataset

    training_data = ClutrrDataset(
        data, False, False, unique_edge_labels, unique_query_labels
    )

    cl_args.edge_types = training_data.num_edge_labels + 1
    cl_args.target_size = training_data.num_query_labels

    training_len = int(0.8 * len(training_data))
    validation_len = len(training_data) - training_len
    training_set, validation_set = torch.utils.data.random_split(
        training_data, [training_len, validation_len]
    )

    collate_fn = partial(
        collate,
        batch_edges_fn=batch_edges_multi,
        num_edge_types=training_data.num_edge_labels + 1,
    )
    data_params = {
        "batch_size": batch_size,
        "shuffle": False,
        "drop_last": False,
        "num_workers": 8,
    }
    train_loader = DataLoader(training_set, **data_params, collate_fn=collate_fn)
    val_loader = DataLoader(validation_set, **data_params, collate_fn=collate_fn)

    num_training_steps = epochs * len(train_loader)
    cl_args.optimizer_args = {"lr": lr}
    cl_args.scheduler_args = {
        "num_warmup_steps": cl_args.num_warmup_steps,
        "num_training_steps": num_training_steps,
    }

    model = EdgeTransformer(cl_args)

    pl_logger = None
    if log_dir is not None:
        from lightning.pytorch.loggers import CSVLogger

        pl_logger = CSVLogger(save_dir=log_dir, name="lightning_logs")
        if logger:
            logger.info(f"Lightning logs → {log_dir}/lightning_logs/")

    accelerator = "gpu" if torch.cuda.is_available() else "cpu"
    if logger:
        if torch.cuda.is_available():
            device_str = f"cuda:{torch.cuda.current_device()} ({torch.cuda.get_device_name(torch.cuda.current_device())})"
        else:
            device_str = "cpu"
        logger.info(f"ET training device: {device_str}")

    trainer = pl.Trainer(
        max_epochs=epochs,
        gradient_clip_val=cl_args.max_grad_norm,
        precision=cl_args.precision,
        logger=pl_logger if pl_logger is not None else True,
        accelerator=accelerator,
        devices=1,
        check_val_every_n_epoch=val_check_interval,
        num_sanity_val_steps=0,
    )

    if logger:
        logger.info("Running baseline validation (epoch 0, untrained model) …")
    baseline_results = trainer.validate(model, val_loader, verbose=False)
    baseline_acc = (
        baseline_results[0].get("val_acc", float("nan"))
        if baseline_results
        else float("nan")
    )
    baseline_loss = (
        baseline_results[0].get("val_loss", float("nan"))
        if baseline_results
        else float("nan")
    )
    if logger:
        logger.info(
            f"Epoch 0 baseline (untrained): val_loss={baseline_loss:.4f}  val_acc={baseline_acc:.4f}  "
            f"(validation every {val_check_interval} epochs)"
        )

    if logger:
        logger.info("Starting training …")

    import time

    start = time.time()
    trainer.fit(model, train_loader, val_loader)
    elapsed = time.time() - start

    best_val_acc = float("nan")
    if "val_acc" in trainer.callback_metrics:
        best_val_acc = float(trainer.callback_metrics["val_acc"])

    if logger:
        logger.info(f"Training finished in {elapsed:.1f}s  (val_acc={best_val_acc:.4f})")

    os.makedirs(os.path.dirname(os.path.abspath(model_output_path)), exist_ok=True)
    torch.save(model.state_dict(), model_output_path)
    if logger:
        logger.info(f"Model saved → {model_output_path}")

    return model_output_path, best_val_acc

