import csv
import ast
import json
import os
import glob
import numpy as np
import re
from typing import Callable, List, Union, Tuple
import torch
from torch import Tensor, LongTensor
from torch.optim import Optimizer
from torch.nn import Module
import random
import logging
import pickle
import math
# from torch_scatter import scatter_sum  # Removed: unused and causes segfault with PyTorch 2.9
from dataclasses import dataclass
import networkx as nx
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score
from torch.utils.data import Dataset

log = logging.getLogger(__name__)
device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')



class StoryDataset(Dataset):
    """Groups queries by story_id. Each __getitem__ returns one story with all queries."""

    def __init__(self, data_dict, unique_edge_labels, unique_query_labels):
        # Reuse existing label encoding
        self.edge_labels_enc, _ = edge_labels_to_indices(data_dict['edge_labels'], unique_edge_labels)
        self.query_labels_enc, _ = query_labels_to_indices(data_dict['query_label'], unique_edge_labels)
        self.query_labels_mh = batch_multihot(self.query_labels_enc, len(unique_edge_labels))

        self.num_edge_labels = len(unique_edge_labels)

        # Group by story_id (contiguous rows)
        self.stories = []
        story_ids = data_dict['story_id']
        for sid in sorted(set(story_ids)):
            idx = [i for i, s in enumerate(story_ids) if s == sid]
            self.stories.append({
                'edges': data_dict['edges'][idx[0]],
                'edge_labels': self.edge_labels_enc[idx[0]],
                'query_edges': [data_dict['query_edge'][i] for i in idx],
                'query_labels': self.query_labels_mh[idx],
            })

    def __len__(self):
        return len(self.stories)

    def __getitem__(self, idx):
        s = self.stories[idx]
        return {
            'edge_index': torch.LongTensor(s['edges']).T,
            'edge_type': torch.LongTensor(s['edge_labels']),
            'query_edges': torch.LongTensor(s['query_edges']),
            'query_labels': s['query_labels'],
        }


class StoryDataset2(StoryDataset):
    """Like StoryDataset but treats every row as its own independent story."""

    def __init__(self, data_dict, unique_edge_labels, unique_query_labels):
        # Encode labels the same way as the parent
        self.edge_labels_enc, _ = edge_labels_to_indices(data_dict['edge_labels'], unique_edge_labels)
        self.query_labels_enc, _ = query_labels_to_indices(data_dict['query_label'], unique_edge_labels)
        self.query_labels_mh = batch_multihot(self.query_labels_enc, len(unique_edge_labels))
        self.num_edge_labels = len(unique_edge_labels)

        # One "story" per row — no grouping
        self.stories = []
        for i in range(len(data_dict['edges'])):
            self.stories.append({
                'edges': data_dict['edges'][i],
                'edge_labels': self.edge_labels_enc[i],
                'query_edges': [data_dict['query_edge'][i]],
                'query_labels': self.query_labels_mh[[i]],
            })


class ClutrrDataset(Dataset):
	def __init__(self, dataset, reverse=False, fp_bp=False,
			     unique_edge_labels=None,unique_query_labels=None):
		super().__init__()
		self.fp_bp = fp_bp
		self.edges = dataset['edges']
		query_labels = []
		for label_list in dataset['query_label']:
			query_labels.extend(label_list)

		#  unify unique edge and query labels
		if unique_edge_labels is None:
			unique_edge_labels = set(find_unique_edge_labels(dataset['edge_labels'])) 
			unique_query_labels = set(query_labels)
			unique_labels = list(unique_edge_labels.union(unique_query_labels))
		else:
			unique_labels = unique_edge_labels
			assert unique_edge_labels == unique_query_labels
		# assert len(unique_labels) == 20

		self.edge_labels, unique_edge_labels = edge_labels_to_indices(dataset['edge_labels'],unique_labels)
		self.query_edge = dataset['query_edge']
		self.query_label, unique_query_labels = query_labels_to_indices(dataset['query_label'],unique_labels)
		
		self.unique_edge_labels = unique_edge_labels
		self.unique_query_labels = unique_query_labels
		self.num_edge_labels = len(unique_edge_labels)
		self.num_query_labels = len(unique_query_labels)

		self.query_label = batch_multihot(self.query_label, self.num_edge_labels)

	
	def __len__(self):
		return len(self.edges)

	def __getitem__(self,index):	
		item = {
			'edge_index': torch.LongTensor(self.edges[index]).permute(1,0),
			'edge_type': torch.LongTensor(self.edge_labels[index]),
			'target_edge_index': torch.LongTensor(self.query_edge[index]).unsqueeze(1),
			'target_edge_type': self.query_label[index],
		}
		if self.fp_bp:
			item['rev_edge_index'] = torch.LongTensor(self.rev_edges[index]).permute(1,0)
			item['rev_edge_type'] = torch.LongTensor(self.rev_edge_labels[index])
		return item


class PathError(Exception):
	"""Raised when the path is invalid"""
	pass

def get_acc(logits: Tensor, target_labels: Tensor):
    return torch.eq(logits.argmax(axis=1), target_labels).sum()/logits.shape[0]

def get_acc_multihot(scores, target_labels, *, threshold=0.5, exact_match=True):
	"""
	Parameters
	----------
	scores   : Tensor (B, C)   raw logits for each class
	labels   : Tensor (B, C)   multi‑hot ground truth in batch dict
	threshold: float           sigmoid cutoff for positive prediction
	exact_match : bool
		• False (default) → micro‑accuracy across all bits
		• True            → sample‑level exact‑match accuracy
	"""
	# 1) convert logits → 0/1 predictions
	preds = (scores.sigmoid() >= threshold).to(scores.dtype)
	if exact_match:
		# every bit must match in the row to be counted correct
		acc = (preds == target_labels).all(dim=1).float().mean().detach()
	else:
		# micro‑accuracy: fraction of correctly predicted bits overall
		acc = (preds == target_labels).float().mean().detach()

	macro_f1 = f1_score(target_labels.cpu(), preds.cpu(), average='macro', zero_division=0)
	micro_f1 = f1_score(target_labels.cpu(), preds.cpu(), average='micro', zero_division=0)

	return acc

def save_model(model: Module, epoch: int, opt: Optimizer, exp_name: str = None, 
			   model_path: str = None) -> None:
	state = {
	"model": model.state_dict(),
	"optimizer": opt.state_dict()
	}
	if not model_path:
		model_path = f"../models/{exp_name}_model_epoch_{epoch}.pth"
	torch.save(state, model_path)


def load_model_state(model_skeleton: Module, model_str: str, optimizer: Optimizer) -> None:
	model = model_skeleton
	model_name = model_str.split('/')[-1]
	exp_name = model_name.split('_model_epoch')[0]
	new_path = f"../results/{exp_name}/{exp_name}_model.pth"
	if os.path.exists(new_path):
		state = torch.load(new_path)
	elif os.path.exists(model_str):
		state = torch.load(model_str)
	else:
		raise PathError(f"Model {model_str} does not exist.")

	log.info(f"Loading {model_name} from checkpoint.")
	try:
		model.load_state_dict(state["model"])
		optimizer.load_state_dict(state["optimizer"])
	except RuntimeError:
		# extra params that didn't exist in the old models are ignored
		pass

	try:
		model.load_state_dict(state["model"])
		optimizer.load_state_dict(state["optimizer"])
	except RuntimeError:
		# extra params that didn't exist in the old models are ignored
		pass


def save_json(data: dict, fname: str) -> None:
	with open(f"{fname}", 'w') as f:
		json.dump(data, f)

	
def set_seed(seed: int = 42) -> None:
    np.random.seed(seed)
    random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    # When running on the CuDNN backend, two further options must be set
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    # Set a fixed value for the hash seed
    os.environ["PYTHONHASHSEED"] = str(seed)
    print(f"Random seed set as {seed}")


	
def read_datafile(filename, remove_not_chains=False):
	edge_ls = []
	edge_labels_ls = []
	query_edge_ls = []
	query_label_ls = []
	true_count = 0
	with open(filename, "r") as f:
		reader = csv.DictReader(f)
		for row in reader:
			true_count += 1
			edges = row['story_edges']
			edges = ast.literal_eval(edges)
			edge_labels = ast.literal_eval(row['edge_types'])
			query_edge = ast.literal_eval(row['query_edge'])
			query_label = row['target']
			is_chain=True
			if remove_not_chains:
				for i in range(len(edges)-1):
					edge_i = edges[i]
					edge_j = edges[i+1]
					if edge_i[0] + 1 != edge_j[0] and edge_i[1] + 1 != edge_j[1]:
						is_chain=False
						break
			if not is_chain:
				continue
			edge_ls.append(edges)
			edge_labels_ls.append(edge_labels)
			query_edge_ls.append(query_edge)
			query_label_ls.append(query_label)

	data = {'edges':edge_ls,'edge_labels':edge_labels_ls,'query_edge':query_edge_ls,'query_label':query_label_ls}

	log.info(f"loaded {filename}: {len(data)} instances.")
	if remove_not_chains:
		log.info(f"removed {true_count - len(edge_ls)}/{true_count} not-chains.")
	return data

def find_unique_edge_labels(ls):
	unique = []
	for labels in ls:
		unique.extend(labels)
	unique = list(set(unique))
	return unique

def edge_labels_to_indices(ls,unique=None):
	if unique is None:
		unique = find_unique_edge_labels(ls)
def find_unique_edge_labels(ls):
	unique = []
	for labels in ls:
		unique.extend(labels)
	unique = list(set(unique))
	return unique

def edge_labels_to_indices(ls,unique=None):
	if unique is None:
		unique = find_unique_edge_labels(ls)

	relabeled = [list(map(lambda y: unique.index(y),x)) for x in ls]
	relabeled = [list(map(lambda y: unique.index(y),x)) for x in ls]
	return relabeled, unique

def query_labels_to_indices(ls,unique=None):
	if unique is None:
		unique = list(set(ls))
	
	# relabeled = list(map(unique.index,ls))
	relabeled = []
	for label_list in ls:
		relabeled_i = list(map(unique.index, label_list))
		relabeled.append(relabeled_i)
	return relabeled, unique


def batch_multihot(batch_indices, num_edge_types, *,
                   dtype=torch.float, device=None):
    """
    batch_indices : list[list[int]]
        e.g. [[13, 14, 15, 17], [0, 7], []]
    num_edge_types: int
        length of the one‑hot axis
    sparse       : if True → returns a sparse COO tensor

    Returns
    -------
    out : (B, num_edge_types) tensor with 1 where the class is present
    """
    B = len(batch_indices)

    # ── flatten row / column coordinates ────────────────────────────
    rows, cols = zip(*[
        (b, idx)                 # b = row, idx = col
        for b, idx_list in enumerate(batch_indices)
        for idx in idx_list
    ]) if any(batch_indices) else ([], [])


    # dense—allocate once, then fill with advanced indexing
    out = torch.zeros(B, num_edge_types, dtype=dtype)
    if rows:                                  # skip if every list empty
        out[torch.tensor(rows, device=device),
            torch.tensor(cols, device=device)] = 1
    
    return out


def load_jsonl(input_path) -> list:
    """
    Read list of objects from a JSON lines file.
    """
    data = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            data.append(json.loads(line.rstrip("\n|\r")))
    print("Loaded {} records from {}".format(len(data), input_path))
    return data

def load_rcc8_file_as_dict(train_fname: str) -> dict:
	edge_ls = []
	edge_labels_ls = []
	query_edge_ls = []
	query_label_ls = []

	with open(train_fname, 'r') as f:
		reader = csv.DictReader(f)
		for row in reader:
			edges = ast.literal_eval(row['edges'])
			edge_labels = ast.literal_eval(row['edge_labels'])
			query_edge = ast.literal_eval(row['query_edge'])
			query_label = ast.literal_eval(row['query_label'])

			edge_ls.append(edges)
			edge_labels_ls.append(edge_labels)
			query_edge_ls.append(query_edge)
			query_label_ls.append(query_label)
	data = {'edges':edge_ls,'edge_labels':edge_labels_ls,'query_edge':query_edge_ls,'query_label':query_label_ls}
	print(f"loaded {train_fname}: {len(edge_ls)} instances.")
	return data
