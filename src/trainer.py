import os
import time

import numpy as np
import torch
import torch.nn as nn
from torch import Tensor
from torch.utils.data import DataLoader
from tqdm import tqdm

import src.globals as glob
import wandb
from src.utils import metrics

class Trainer():

    def __init__(self, model : nn.Module, device, criterion, optimizer) : #TODO qualcosa 
        
        self.device = device 

        model.to(self.device)
        self.model = model

        self.criterion = criterion.to(self.device) if isinstance(criterion, nn.Module) else criterion 
        self.optimizer = optimizer

        self.models_dir = glob.BASE_PATH / 'models'


    def train_loop(self, dataloader : DataLoader):

        batch_size = dataloader.batch_size
        dataset_size = len(dataloader.dataset)

        start_time = time.perf_counter()

        tot_loss = 0
        
        #aggregate all the predictions and corresponding true labels (and claim ids) in tensors 
        all_pred , all_targ = np.empty(dataset_size), np.empty(dataset_size)

        self.model.train()
    
        for batch_id, batch_data in enumerate(tqdm(dataloader)):

            self.optimizer.zero_grad()            

            predictions : Tensor = self.model(batch_data)   #generate predictions 
            predictions = predictions.squeeze(1)

            loss = self.criterion(predictions.float(), batch_data['labels'].float())      #compute the loss 

            #backward pass 
            loss.backward()
            self.optimizer.step()

            pred = (predictions > 0.0 ).detach().int().cpu().numpy()           #get class label 

            start = batch_id * batch_size
            end = start + batch_size

            #concatenate the new tensors with the one computed in previous steps
            all_pred[start:end] = pred 
            all_targ[start:end] = batch_data['labels'].detach().cpu().numpy()       

            tot_loss += loss.item()    #accumulate batch loss 


        acc, f1, prec, rec = metrics(all_targ,all_pred)

        loss = tot_loss/(batch_id+1)    #mean loss 

        end_time = time.perf_counter()

        return loss, acc, f1, prec, rec, end_time-start_time


    def eval_loop(self, dataloader : DataLoader):

        batch_size = dataloader.batch_size
        dataset_size = len(dataloader.dataset)

        start_time = time.perf_counter()

        tot_loss = 0
        
        #aggregate all the predictions and corresponding true labels (and claim ids) in tensors 
        all_pred , all_targ = np.empty(dataset_size), np.empty(dataset_size)
        
        self.model.eval()   #model in eval mode 
        
        with torch.no_grad(): #without computing gradients since it is evaluation loop
        
            for batch_id, batch_data in enumerate(tqdm(dataloader)):
                
                predictions : Tensor = self.model(batch_data)   #generate predictions 
                predictions = predictions.squeeze(1)

                loss = self.criterion(predictions.float(), batch_data['labels'].float())      #compute the loss 

                pred = (predictions > 0.0 ).detach().int().cpu().numpy()        #get class label 
                start = batch_id * batch_size
                end = start + batch_size

                #concatenate the new tensors with the one computed in previous steps
                all_pred[start:end] = pred 
                all_targ[start:end] = batch_data['labels'].detach().cpu().numpy()     

                tot_loss += loss.item()   #accumulate batch loss 
                
        acc, f1, prec, rec = metrics(all_targ,all_pred)

        loss = tot_loss/(batch_id+1)   #mean loss 

        end_time = time.perf_counter()

        return loss, acc, f1, prec, rec, end_time-start_time

    
    def train_and_eval(self, train_loader, val_loader, num_epochs):
        """
            Runs the train and eval loop and keeps track of all the metrics of the training model 
        """
        best_f1 = -1   #init best f1 score

        for epoch in range(1, num_epochs+1): #epoch loop

            start_time = time.perf_counter()

            print(f'Starting epoch {epoch}')

            train_metrics = self.train_loop(train_loader) 
            val_metrics = self.eval_loop(val_loader) 
            
            end_time = time.perf_counter()

            tot_epoch_time = end_time-start_time          

            train_epoch_loss, train_epoch_acc, train_epoch_f1, train_epoch_prec, train_epoch_rec, train_epoch_time = train_metrics
            val_epoch_loss, val_epoch_acc, val_epoch_f1, val_epoch_prec, val_epoch_rec, val_epoch_time = val_metrics

            if val_epoch_f1 >= best_f1:
                best_f1 = val_epoch_f1
                if not os.path.exists(self.models_dir):        
                    os.makedirs(self.models_dir)
                torch.save(self.model.state_dict(),self.models_dir/ f'{self.model.name()}.pt')  

            # wandb logs 
            wandb.log({'train/loss': train_epoch_loss, 'train/acc': train_epoch_acc, 'train/f1': train_epoch_f1,
                       'train/prec': train_epoch_prec, 'train/rec': train_epoch_rec, 'train/time': train_epoch_time,
                       'val/loss': val_epoch_loss, 'val/acc': val_epoch_acc, 'val/f1': val_epoch_f1,
                       'val/prec': val_epoch_prec, 'val/rec': val_epoch_rec, 'val/time' : val_epoch_time, 
                       'lr': self.optimizer.param_groups[0]['lr'], 'epoch': epoch})
        
            print(f'Total epoch Time: {tot_epoch_time:.4f}')
            print(f'Train Loss: {train_epoch_loss:.3f} | Train Acc: {train_epoch_acc*100:.2f}% | Train F1: {train_epoch_f1:.2f}')
            print(f'Val. Loss: {val_epoch_loss:.3f} | Val. Acc: {val_epoch_acc*100:.2f}% | Val. F1: {val_epoch_f1:.2f}')
    
    def test(self, test_loader):

        print('loading model state from folder')
        self.model.load_state_dict(torch.load(f'models/{self.model.name()}.pt'))
        print('loaded')

        test_metrics = self.eval_loop(test_loader)
        test_epoch_loss, test_epoch_acc, test_epoch_f1, test_epoch_prec, test_epoch_rec, test_epoch_time = test_metrics

        print(f'Test -> Loss: {test_epoch_loss:.3f} | Acc: {test_epoch_acc:.3f} | F1: {test_epoch_f1:.3f} | Prec: {test_epoch_prec:.3f} | Rec: {test_epoch_rec:.3f} ')

        
        