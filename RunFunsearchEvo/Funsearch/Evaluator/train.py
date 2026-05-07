import os
import argparse
import re
import random
import numpy as np
import torch
from torch.utils.data import DataLoader
import lightning.pytorch as pl
from pytorch_lightning import seed_everything
import time
from typing import List, Tuple, Callable


from Evaluator.model import EdgeTransformer
import json
from Funsearch.Evaluator.eval_utils import ClutrrDataset, set_seed
from Funsearch.Evaluator.eval_utils import log, load_rcc8_file_as_dict
import pickle

torch.set_float32_matmul_precision('medium')

def create_parser():
	parser = argparse.ArgumentParser()
	parser.add_argument('--model_type',type=str, default="edge_transformer")
	parser.add_argument('--lr',type=float, default=1e-3)
	parser.add_argument('--epochs',type=int, default=100)
	parser.add_argument('--batch_size',type=int, default=32)
	parser.add_argument('--num_message_rounds',type=int, default=2)
	parser.add_argument('--dropout',type=float, default=0.2)
	parser.add_argument('--dim',type=int, default=256)
	parser.add_argument('--num_heads',type=int, default=32)
	parser.add_argument('--max_grad_norm',type=float,default=1.0)
	parser.add_argument('--share_layers', dest='share_layers', action='store_true')
	parser.add_argument('--no_share_layers', dest='share_layers', action='store_false')
	parser.set_defaults(share_layers=True)
	parser.add_argument('--data_path',type=str,default='data_9b2173cf')
	parser.add_argument('--lesion_values', action='store_true')
	parser.add_argument('--lesion_scores',  action='store_true')
	parser.add_argument('--update_relations', type=str, default='True') #this is for relation transformer
	parser.add_argument('--flat_attention', action='store_true')
	parser.add_argument('--zero_init', dest='zero_init', action='store_true')  #initialization strategy for relation aware transformer
	parser.add_argument('--random_init', dest='zero_init', action='store_false')
	parser.set_defaults(zero_init=True)
	parser.add_argument('--optimizer',type=str,default="Adam")
	parser.add_argument('--scheduler',type=str,default="linear_warmup")
	parser.add_argument('--num_warmup_steps',type=int,default=100)
	parser.add_argument('--ff_factor',type=int,default=4)
	parser.add_argument('--log_file',type=str,default='logs/clutrr_log_file.csv')
	parser.add_argument('--precision',type=int,default=32,choices=[16,32])
	parser.add_argument('--seed',type=int,default=42)
	parser.add_argument('--dataset_type',type=str, default='no_ambiguity_v2')
	parser.add_argument('--input_rep',type=str, default='multiedge')
	parser.add_argument('--exp_name',type=str,default="edget")
	return parser

def parse_args(args=None):
	parser = create_parser()
	cl_args = parser.parse_args(args)
	if str(cl_args.update_relations) == 'False':
		cl_args.update_relations = False
	else:
		cl_args.update_relations = True
	return cl_args

def train(cl_args):

	train_loader, validation_loader, test_loaders, test_filenames, cl_args = load_files(cl_args.dataset_type)
	
	optimizer_args = {'lr':cl_args.lr}
	num_training_steps = cl_args.epochs*len(train_loader)
	scheduler_args = {'num_warmup_steps':cl_args.num_warmup_steps,'num_training_steps':num_training_steps}
	cl_args.optimizer_args = optimizer_args
	cl_args.scheduler_args = scheduler_args
	

	trainer = pl.Trainer(
			# gpus=1,
			max_epochs=cl_args.epochs,
			gradient_clip_val=cl_args.max_grad_norm,
			# progress_bar_refresh_rate=1,
			precision=cl_args.precision
		)

	if cl_args.model_type=='edge_transformer':
		model = EdgeTransformer(cl_args)
	################### PERSONAL MOD ###################
	path = f'{cl_args.exp_name}.pth'
	if not os.path.exists(path):
		start = time.time()
		trainer.fit(model,train_loader,validation_loader)
		end = time.time()
		print(f"Training Time taken: {end-start}")

		torch.save(model.state_dict(), path)
	else:
		model.load_state_dict(torch.load(path))
	################### PERSONAL MOD ###################
	# test_acc_schema = {'test_accs': {}, 'macro_f1s': {}, 'micro_f1s': {}}
	# start = time.time()

#Load data##
def load_dataset(data_filename: str, unique_edge_labels: list = None, 
				 unique_query_labels: list = None, dataset_type='clutrr') -> ClutrrDataset:
    pfname = data_filename + '.pkl'
    if not os.path.exists(pfname):
        if dataset_type in ['rcc8', 'interval', 'ambiguity', 'no_ambiguity', 'no_ambiguity_v2',]:
            print(data_filename)
            data = load_rcc8_file_as_dict(data_filename)
            data = ClutrrDataset(data, False, False, unique_edge_labels, unique_query_labels)
            pickle.dump(data, open(pfname, 'wb'))
        else:
            raise ValueError(f"Unknown dataset type: {dataset_type}")
    else:
        log.info(f"preprocessed data file loaded from: {pfname}")
        data = pickle.load(open(pfname, 'rb'))
        # assert len(data.unique_edge_labels) == 20
    return data

def batch_edges(edges,edge_labels, num_edge_types):
	batch_size = len(edges)
	lens = torch.tensor(list(map(lambda x: torch.max(x)+1,edges)))
	max_len = max(lens)

	mask = torch.arange(max_len)[None, :] >= lens[:, None]

	batch = []
	for i in range(batch_size):
		s = torch.zeros(max_len,max_len).long()
		edge = edges[i]
		lab = edge_labels[i]
		s[edge[:,0],edge[:,1]] = lab
		batch.append(s)
	batch = torch.stack(batch)
	return batch, mask

def batch_edges_multi(
	edges: List[torch.Tensor],
	edge_labels: List[torch.Tensor],
	num_edge_types: int | None = None):

	B = len(edges)
	lens = torch.tensor(list(map(lambda x: torch.max(x)+1,edges)))
	max_len = max(lens)
	mask = torch.arange(max_len)[None, :] >= lens[:, None]

	batched = torch.zeros(
		(B, num_edge_types, max_len, max_len), dtype=torch.float
	)
	# print('edge types:', num_edge_types)
	for i, (e, lab) in enumerate(zip(edges, edge_labels)):
		# Advanced indexing: shapes all (Eᵢ,)
		batched[i, lab, e[:, 0], e[:, 1]] = 1.

	return batched, mask

def collate(data, batch_edges_fn,num_edge_types=None):
	batch_size = len(data)
	edges = [d['edge_index'].permute(1,0) for d in data]
	edge_labels = [d['edge_type'] for d in data]
	query_edge = [d['target_edge_index'].squeeze(1) for d in data]
	query_label = [d['target_edge_type'] for d in data]

	batched_edges, mask = batch_edges_fn(edges,edge_labels, num_edge_types=num_edge_types)
	batched_query_edges = torch.stack(query_edge)
	batched_query_edges = torch.cat((torch.arange(batch_size).unsqueeze(1),batched_query_edges),dim=1)


	if isinstance(query_label[0], torch.Tensor):
		batched_query_labels = torch.stack(query_label)
	else:
		batched_query_labels = torch.tensor(query_label)
	# print('batched_query_labels:', batched_query_labels.shape)

	batched = {}
	batched['batched_graphs']=batched_edges
	batched['target_edge_index'] = batched_query_edges
	batched['target_edge_type'] = batched_query_labels
	batched['masks'] = mask

	return batched


def story_collate(data, num_edge_types):
    """Collate single story with Q queries. Reuses batch_edges_multi."""
    item = data[0]
    edges = [item['edge_index'].T]
    edge_labels = [item['edge_type']]

    batched_graphs, mask = batch_edges_multi(edges, edge_labels, num_edge_types)

    Q = len(item['query_edges'])
    query_edges = torch.cat([torch.zeros(Q, 1, dtype=torch.long), item['query_edges']], dim=1)

    return {
        'batched_graphs': batched_graphs,
        'target_edge_index': query_edges,
        'target_edge_type': item['query_labels'],
        'masks': mask,
    }

from functools import partial

def make_data_loader(data: ClutrrDataset, cl_args: argparse.Namespace):
    data_params = {'batch_size': cl_args.batch_size,
                'shuffle': False,
                'drop_last':False,
                'num_workers':8
                }
    if cl_args.input_rep == 'multiedge':
        collate_fn = partial(collate, batch_edges_fn=batch_edges_multi, num_edge_types=data.num_edge_labels+1)
    else:
        collate_fn = partial(collate, batch_edges_fn=batch_edges)
    return DataLoader(data, **data_params,collate_fn=collate_fn)

def load_files(cl_args, dataset_type='no_ambiguity_v2'):

    cl_args = parse_args([])
    cl_args.dataset_type = dataset_type

    assert dataset_type == 'no_ambiguity_v2'
    train_filename = f'train_no_ambig_new.csv'
    test_filenames = []

    data_params = {'batch_size': cl_args.batch_size,
                'shuffle': False,
                'drop_last':False,
                'num_workers':8
                }

    # load the unique edge labels and query labels from the pickle file
    unique_edge_labels, unique_query_labels = pickle.load(open('unique_labels.pkl', 'rb'))

    training_data = load_dataset(train_filename, unique_edge_labels, unique_query_labels, dataset_type=dataset_type)

    cl_args.edge_types = training_data.num_edge_labels+1
    cl_args.target_size = training_data.num_query_labels

    training_len = int(0.8*len(training_data))
    validation_len = len(training_data) - training_len
    training_set, validation_set = torch.utils.data.random_split(training_data, [training_len, validation_len])

    if cl_args.input_rep == 'multiedge':
        collate_fn: Callable = partial(collate, batch_edges_fn=batch_edges_multi, num_edge_types=training_data.num_edge_labels+1)
    else:
        collate_fn: Callable = partial(collate, batch_edges_fn=batch_edges)

    training_loader = DataLoader(training_set, **data_params,collate_fn=collate_fn)
    validation_loader = DataLoader(validation_set, **data_params,collate_fn=collate_fn)
        
        
    test_loaders = []

    return training_loader,validation_loader,test_loaders,test_filenames, cl_args


if __name__=="__main__":
	cl_args = parse_args([])
	set_seed(cl_args.seed)
	train(cl_args)