from __future__ import annotations

import os
import pickle
from functools import partial
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import f1_score
from torch.utils.data import DataLoader

from Funsearch.Evaluator.eval_utils import StoryDataset, load_rcc8_file_as_dict
from Funsearch.Evaluator.model import EdgeTransformer
from Funsearch.Evaluator.train import parse_args, story_collate


def checkpoint_to_path(ckpt_path: str, output_pth_path: str | None = None) -> str:
    """Convert a Lightning `.ckpt` to a plain `.pth` state-dict file."""
    if output_pth_path is None:
        base = ckpt_path[:-5] if ckpt_path.endswith(".ckpt") else ckpt_path
        output_pth_path = base + ".pth"

    ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    if "state_dict" not in ckpt:
        raise ValueError(
            f"{ckpt_path!r} does not look like a Lightning checkpoint (no 'state_dict')."
        )
    torch.save(ckpt["state_dict"], output_pth_path)
    return output_pth_path


def load_et_model(
    *,
    model_path: str,
    unique_labels_path: Optional[str] = None,
    device: str = "cuda",
) -> Tuple[EdgeTransformer, Any, Any, Any]:
    if unique_labels_path is None:
        unique_labels_path = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "..",
                "Funsearch",
                "Evaluator",
                "unique_labels.pkl",
            )
        )

    with open(unique_labels_path, "rb") as f:
        unique_edge_labels, unique_query_labels = pickle.load(f)

    cl_args = parse_args([])
    cl_args.edge_types = len(unique_edge_labels) + 1
    cl_args.target_size = len(unique_query_labels)

    if device == "cuda" and not torch.cuda.is_available():
        device = "cpu"

    model = EdgeTransformer(cl_args)

    raw = torch.load(model_path, map_location="cpu", weights_only=False)
    state_dict = raw["state_dict"] if isinstance(raw, dict) and "state_dict" in raw else raw
    model.load_state_dict(state_dict)

    model.eval()
    if device != "cpu":
        model = model.to(device)

    return model, cl_args, unique_edge_labels, unique_query_labels


def _csv_to_story_loader(
    *,
    csv_path: str,
    unique_edge_labels: list,
    unique_query_labels: list,
    max_samples: Optional[int] = None,
    logger=None,
) -> DataLoader:
    pkl_cache = csv_path + ".pkl"
    if os.path.exists(pkl_cache):
        os.remove(pkl_cache)

    data = load_rcc8_file_as_dict(csv_path)

    df = pd.read_csv(csv_path)
    if "story_id" in df.columns:
        data["story_id"] = df["story_id"].tolist()
    elif "story_index" in df.columns:
        data["story_id"] = df["story_index"].tolist()
    else:
        data["story_id"] = list(range(len(data["edges"])))

    if max_samples is not None and len(data["edges"]) > max_samples:
        import random as _rng

        n_total = len(data["edges"])
        keep = sorted(_rng.sample(range(n_total), max_samples))
        for key in ("edges", "edge_labels", "query_edge", "query_label"):
            data[key] = [data[key][i] for i in keep]
        data["story_id"] = [data["story_id"][i] for i in keep]
        if logger:
            logger.info(f"  Sampled {max_samples} / {n_total} rows from {csv_path}")

    dataset = StoryDataset(data, unique_edge_labels, unique_query_labels)
    num_edge_types = len(unique_edge_labels) + 1
    collate_fn = partial(story_collate, num_edge_types=num_edge_types)
    return DataLoader(dataset, batch_size=1, shuffle=False, collate_fn=collate_fn)


def evaluate_model_on_csv(
    *,
    model: EdgeTransformer,
    csv_path: str,
    unique_edge_labels: list,
    unique_query_labels: list,
    device: str = "cuda",
    max_samples: Optional[int] = None,
    logger=None,
) -> Dict[str, Any]:
    loader = _csv_to_story_loader(
        csv_path=csv_path,
        unique_edge_labels=unique_edge_labels,
        unique_query_labels=unique_query_labels,
        max_samples=max_samples,
        logger=logger,
    )

    if device == "cuda" and not torch.cuda.is_available():
        if logger:
            logger.warning("CUDA requested but not available — falling back to CPU")
        device = "cpu"

    metrics: Dict[str, list] = {"acc": [], "macro_f1": [], "micro_f1": [], "loss": []}

    model.eval()
    with torch.no_grad():
        for story_idx, batch in enumerate(loader):
            batch = {
                k: v.to(device) if isinstance(v, torch.Tensor) else v for k, v in batch.items()
            }
            try:
                loss, logits = model._calculate_loss(batch)
            except RuntimeError as e:
                if device != "cpu" and ("CUDA" in str(e) or "device-side" in str(e)):
                    if logger:
                        logger.warning(
                            f"CUDA error on story {story_idx}, falling back to CPU: {e}"
                        )
                    torch.cuda.empty_cache()
                    model = model.cpu()
                    device = "cpu"
                    batch = {
                        k: v.cpu() if isinstance(v, torch.Tensor) else v for k, v in batch.items()
                    }
                    loss, logits = model._calculate_loss(batch)
                else:
                    raise

            labels = batch["target_edge_type"].to(logits.dtype)
            preds = (logits.sigmoid() >= 0.5).to(logits.dtype)

            acc = (preds == labels).all(dim=1).float().mean().item()
            macro = f1_score(
                labels.cpu().numpy(),
                preds.cpu().numpy(),
                average="macro",
                zero_division=0,
            )
            micro = f1_score(
                labels.cpu().numpy(),
                preds.cpu().numpy(),
                average="micro",
                zero_division=0,
            )

            metrics["acc"].append(acc)
            metrics["macro_f1"].append(macro)
            metrics["micro_f1"].append(micro)
            metrics["loss"].append(loss.item())

    if logger:
        n = len(metrics["acc"])
        logger.info(
            f"  {csv_path}: {n} stories, mean_acc={np.mean(metrics['acc']):.4f}, "
            f"mean_macro_f1={np.mean(metrics['macro_f1']):.4f}"
        )

    return metrics


def evaluate_model_on_csvs(
    *,
    model_path: str,
    test_csv_paths: list[str],
    unique_labels_path: Optional[str] = None,
    device: str = "cuda",
    max_samples: Optional[int] = None,
    logger=None,
) -> pd.DataFrame:
    model, _cl_args, uel, uql = load_et_model(
        model_path=model_path, unique_labels_path=unique_labels_path, device=device
    )

    rows: list[dict] = []
    for csv_path in test_csv_paths:
        if not os.path.isfile(csv_path):
            if logger:
                logger.warning(f"Skipping missing file: {csv_path}")
            continue
        if logger:
            logger.info(f"Evaluating on {csv_path} …")

        m = evaluate_model_on_csv(
            model=model,
            csv_path=csv_path,
            unique_edge_labels=uel,
            unique_query_labels=uql,
            device=device,
            max_samples=max_samples,
            logger=logger,
        )

        rows.append(
            {
                "test_csv": os.path.basename(csv_path),
                "test_csv_full_path": csv_path,
                "num_stories": len(m["acc"]),
                "mean_acc": float(np.mean(m["acc"])),
                "std_acc": float(np.std(m["acc"])),
                "mean_macro_f1": float(np.mean(m["macro_f1"])),
                "std_macro_f1": float(np.std(m["macro_f1"])),
                "mean_micro_f1": float(np.mean(m["micro_f1"])),
                "std_micro_f1": float(np.std(m["micro_f1"])),
                "mean_loss": float(np.mean(m["loss"])),
                "std_loss": float(np.std(m["loss"])),
            }
        )

    summary_df = pd.DataFrame(rows)
    if logger:
        logger.info(f"\n{summary_df.to_string(index=False)}")
    return summary_df

