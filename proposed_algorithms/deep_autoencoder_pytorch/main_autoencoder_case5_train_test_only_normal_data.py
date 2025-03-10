# -*- coding: utf-8 -*-
"""
    "abnormal detection by reconstruction errors"
    # 0 is normal, 1 is abnormal

    process:
        1) After training, then save model firstly.
        2) Then laod model, test on different attack data.

    Case4:
        Normal data:
            sess_normal_0

        Attack data:
            sess_DDoS_Excessive_GET_POST
            sess_DDoS_Multi_VERB_Single_Request
            sess_DDoS_Recursive_GET
            sess_DDoS_Slow_POST_Two_Arm_HTTP_server_wait
            sess_DDoS_SlowLoris_Two_Arm_HTTP_server_wait


    Case4:  (no shuffle)
        Train set : (0.7 * all_normal_data)
        Val_set:  (0.1*all_normal_data)
        Test_set: (0.2*all_normal_data+ 1.0*all_abnormal_data)


     Created at :
        2018/11/08

    Version:
        0.3.0

    Requirements:
        python 3.x
        Sklearn 0.20.0

    Author:

    Note:
        # Python's standard out is buffered (meaning that it collects some of the data "written" to standard out before it writes it to the terminal). Calling sys.stdout.flush() forces it to "flush" the buffer, meaning that it will write everything in the buffer to the terminal, even if normally it would wait before doing so.
        method 1: (in each print, using "flush" keyword in 'print' function (since python 3.3))
            print('', flush=True)
        method 2: (change the default for the print function by using functools.partial on the global scope of a module)
            import functools
            print = functools.partial(print, flush=True)

            >>> print = functools.partial(print, flush=True)
            >>> print
            functools.partial(<built-in function print>, flush=True)
        method 3:
            import sys
            sys.standout.flush()
"""
import argparse
import functools
import os
import sys
import time
from collections import Counter

import numpy as np
import torch
import torch.utils.data as Data
from sklearn.metrics import confusion_matrix
from sys_path_export import *  # it is no need to do in IDE environment, however, it must be done in shell/command environment
from torch import nn
from torch.utils.data import DataLoader

from utilities.CSV_Dataloader import open_file
from utilities.common_funcs import show_data, split_normal2train_val_test_from_files, show_data_2


def print_net(net, describe_str='Net'):
    """

    :param net:
    :param describe_str:
    :return:
    """
    num_params = 0
    for param in net.parameters():
        num_params += param.numel()

    print(describe_str, net)
    print('Total number of parameters: %d' % num_params)


class AutoEncoder(nn.Module):
    def __init__(self, in_dim, epochs=2, show_flg=False):
        """

        :param in_dim:
        :param epochs:
        """
        super().__init__()

        self.epochs = epochs
        self.learning_rate = 1e-3
        self.batch_size = 64
        self.stop_early_flg = False  # stop training

        self.show_flg = show_flg

        self.num_features_in = in_dim
        self.h_size = 16
        self.num_latent_features = 10
        self.num_features_out = self.num_features_in

        self.encoder = nn.Sequential(
            nn.Linear(self.num_features_in, self.h_size * 8),
            nn.LeakyReLU(True),
            nn.Linear(self.h_size * 8, self.h_size * 4),
            nn.LeakyReLU(True),
            nn.Linear(self.h_size * 4, self.h_size * 2),
            nn.LeakyReLU(True),
            nn.Linear(self.h_size * 2, self.num_latent_features))

        self.decoder = nn.Sequential(
            nn.Linear(self.num_latent_features, self.h_size * 2),
            nn.LeakyReLU(True),
            nn.Linear(self.h_size * 2, self.h_size * 4),
            nn.LeakyReLU(True),
            nn.Linear(self.h_size * 4, self.h_size * 8),
            nn.LeakyReLU(True),
            nn.Linear(self.h_size * 8, self.num_features_in)
        )

        if self.show_flg:
            print_net(self.encoder, describe_str='Encoder')
            print_net(self.decoder, describe_str='Decoder')

        self.criterion = nn.MSELoss(reduction='elementwise_mean')
        self.optimizer = torch.optim.Adam(
            self.parameters(), lr=self.learning_rate, weight_decay=1e-5)

    def forward(self, x):
        """

        :param x:
        :return:
        """
        x1 = self.encoder(x)
        x = self.decoder(x1)
        return x

    def train(self, train_set, val_set):
        """

        :param train_set:
        :param val_set:
        :return:
        """
        if len(train_set) == 0 or len(val_set) == 0:
            print('data set is not right.')
            return -1
        print('train_set shape is %s, val_set size is %s' % (train_set[0].shape, val_set[0].shape))
        assert self.num_features_in == train_set[0].shape[1]

        X_train = train_set[0]
        self.train_set = Data.TensorDataset(torch.Tensor(X_train),
                                            torch.Tensor(X_train))  # only use features data to train autoencoder
        dataloader = DataLoader(self.train_set, batch_size=self.batch_size, shuffle=True)
        X_val = val_set[0]
        self.val_set = Data.TensorDataset(torch.Tensor(X_val), torch.Tensor(X_val))
        self.results = {'train_set': {'acc': [], 'auc': []}, 'val_set': {'acc': [], 'auc': []}}
        self.loss = {'train_loss': [], 'val_loss': []}
        cnt = 0
        for epoch in range(self.epochs):
            loss_epoch = torch.tensor(0.0)
            tmp = []
            for iter, (batch_X, _) in enumerate(dataloader):
                # # ===================forward=====================
                output = self.forward(batch_X)
                loss = self.criterion(output, batch_X)
                tmp.append(loss)
                # print('iter=%d, batch_size=%s, loss=%f'%(iter, batch_X.shape, loss))
                # ===================backward====================
                self.optimizer.zero_grad()
                loss.backward()
                self.optimizer.step()
                loss_epoch += loss
            # show_data(tmp,fig_label='train_batch_loss')
            # assert  loss_epoch.data / len(dataloader) == np.asarray(tmp, dtype=float)
            # self.loss['train_loss'].append(loss.data)  #
            loss = loss_epoch.data / len(dataloader)
            self.loss['train_loss'].append(loss.data)
            val_output = self.forward(self.val_set.tensors[0])
            val_loss = self.criterion(val_output, self.val_set.tensors[1])
            self.loss['val_loss'].append(val_loss.data)
            if self.stop_early_flg:
                accumulate_flg = False
                if len(self.loss['val_loss']) > 5:
                    if val_loss > self.loss['val_loss'][-2]:
                        accumulate_flg = True
                        accumulate_cnt = accumulate_cnt + 1 if accumulate_flg else 0
                        if accumulate_cnt > 20:
                            print('training stop in advance.')
                            break

            print('epoch [{:d}/{:d}], train_loss:{:.4f}, val_loss:{:.4f}'.format(epoch + 1, self.epochs, loss.data,
                                                                                 val_loss.data))
            sys.stdout.flush()  # Since Python 3.3, you can force the normal print() function to flush without the need to use sys.stdout.flush(); just set the "flush" keyword argument to true.
            # Python's standard out is buffered (meaning that it collects some of the data "written" to standard out before it writes it to the terminal). Calling sys.stdout.flush() forces it to "flush" the buffer, meaning that it will write everything in the buffer to the terminal, even if normally it would wait before doing so.
            # if epoch % 10 == 0:
            #     # pic = to_img(output.cpu().input_data)
            #     # save_image(pic, './mlp_img/image_{}.png'.format(epoch))
        self.T = torch.Tensor([np.min(self.loss['train_loss'])])
        print('the minimal loss on train_set is %f' % self.T.data, flush=True)

        if self.show_flg:
            # show_data(self.loss['train_loss'], x_label='epochs', y_label='Train_loss', fig_label='Train_loss',
            #           title='training loss on training process')
            # show_data(self.loss['val_loss'], x_label='epochs', y_label='Val_loss', fig_label='Val_loss',
            #           title='val_set loss on training process')
            show_data_2(self.loss['train_loss'], self.loss['val_loss'], title='training loss on training process')

    def evaluate(self, test_set, threshold=0.1):
        """

        :param test_set:
        :param threshold:
        :return:
        """
        X = torch.Tensor(test_set[0])
        y_true = test_set[1]

        # self.T = torch.Tensor([0.0004452318244148046])  # based on the training loss.
        self.T = torch.Tensor([threshold])
        # Step 1. predict output
        AE_outs = self.forward(X)

        # Step 2. comparison with Threshold.
        y_preds = []
        num_abnormal = 0
        self.false_alarm_lst = []
        print('Threshold(T) is ', self.T.data.tolist())
        for i in range(X.shape[0]):
            # if torch.dist(AE_outs, X, 2) > self.T:
            # if torch.norm((AE_outs[i] - X[i]), 2) > self.T:
            distance_error = self.criterion(AE_outs[i], X[i])
            if distance_error > self.T:
                # print('abnormal sample.')
                y_preds.append('1')  # 0 is normal, 1 is abnormal
                if y_true[i] == 0:  # save predict error: normal are recognized as attack
                    num_abnormal += 1
                    self.false_alarm_lst.append([i, distance_error.data, X[i].data])
            else:
                y_preds.append('0')

        # Step 3. achieve the evluation standards.
        print('No. of abnormal samples (false alarm) is ', num_abnormal)
        y_preds = np.asarray(y_preds, dtype=int)
        cm = confusion_matrix(y_pred=y_preds, y_true=y_true)
        print('Confusion matrix:\n', cm)
        acc = 100.0 * sum(y_true == y_preds) / len(y_true)
        print('Acc: %.2f%%' % acc)

        return acc, cm


def save_model(model, out_file='../log/autoencoder.pth'):
    """

    :param model:
    :param out_file:
    :return:
    """
    out_dir = os.path.split(out_file)[0]
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
    torch.save(model, out_file)

    return out_file


def evaluate_model(model, test_set, iters=10,
                   fig_params={'x_label': 'evluation times', 'y_label': 'accuracy on val set', 'fig_label': 'acc',
                               'title': 'accuracy on val set'}):
    """

    :param model:
    :param test_set:
    :param iters:
    :param fig_params:
    :return:
    """
    assert len(test_set) > 0

    if iters == 1:
        thres = model.T.data
        print("Evaluation:%d/%d threshold = %f" % (1, iters, thres))
        test_set_acc, test_set_cm = model.evaluate(test_set, threshold=thres)
        max_acc_thres = (test_set_acc, thres, 1)
    else:
        i = 0
        test_acc_lst = []
        thres_lst = []
        max_acc_thres = (0.0, 0.0)  # (acc, thres)
        for thres in np.linspace(start=10e-3, stop=(model.T.data) * 1, num=iters, endpoint=True):
            i += 1
            print("\nEvaluation:%d/%d threshold = %f" % (i, iters, thres))
            test_set_acc, test_set_cm = model.evaluate(test_set, threshold=thres)
            test_acc_lst.append(test_set_acc)
            thres_lst.append(thres)
            if test_set_acc > max_acc_thres[0]:
                max_acc_thres = (test_set_acc, thres, i)

        if model.show_flg:
            show_data(data=thres_lst, x_label='evluation times', y_label='threshold', fig_label='thresholds',
                      title='thresholds variation')
            show_data(data=test_acc_lst, x_label=fig_params['x_label'], y_label=fig_params['y_label'], fig_label='acc',
                      title=fig_params['title'])

    return max_acc_thres, test_set_acc, test_set_cm


def evaluate_model_new(model, test_set_without_abnormal_data, u_normal, std_normal, test_files_lst, label='1'):
    """

    :param AE_model:
    :param test_set_without_abnormal_data:
    :param u_normal:
    :param std_normal:
    :param test_files_lst:
    :return:
    """
    idx_f = 1
    print('test_files_lst:', test_files_lst)
    for test_file_tmp in test_files_lst:
        print('\n[%d/%d] test_file:%s' % (idx_f, len(test_files_lst), test_file_tmp))
        (X_attack_data, y_attack_data) = test_set_without_abnormal_data
        (X_tmp, y_tmp) = open_file(test_file_tmp, label=label)
        X_attack_data = np.concatenate((X_attack_data, np.asarray(X_tmp, dtype=float)), axis=0)
        y_attack_data = np.concatenate(
            (np.reshape(y_attack_data, (len(y_attack_data))), np.reshape(np.asarray(y_tmp, dtype=int), (len(y_tmp)))))
        test_set_original = (X_attack_data, y_attack_data)
        print('\'test_set\' includes 0.2 normal_data (%d) + 1.0*attack_data (%d) which comes from \'%s\'' % (
            len(test_set_without_abnormal_data[1]), len(X_attack_data), test_file_tmp))
        test_set = ((X_attack_data - u_normal) / std_normal, y_attack_data)
        print('test_set:%s' % Counter(test_set_without_abnormal_data[1]))
        evaluate_model(model, test_set, iters=1)  # for autoencoder
        # print(acc, cm)
        # model.evaluate(test_set, name='test_set')

        # step 4.2 out predicted values in descending order
        false_samples_lst = sorted(model.false_alarm_lst, key=lambda l: l[1],
                                   reverse=True)  # for second dims, sorted(li,key=lambda l:l[1], reverse=True)
        num_print = 10
        print('The normal samples are recognized as attack samples are as follow in the first %d samples:', num_print)
        if len(false_samples_lst) < num_print:
            num_print = len(false_samples_lst)
        np.set_printoptions(suppress=True)  # Suppresses the use of scientific notation for small numbers in numpy array
        for i in range(num_print):
            v_by_std_u = np.asarray(false_samples_lst[i][2].data.tolist(), dtype=float) * std_normal + u_normal
            print('i=%d' % i, ' <index in test_set, distance_error, norm_vale>', false_samples_lst[i], ' v*std+u:',
                  v_by_std_u, '=>original vaule in test set:', test_set_original[0][false_samples_lst[i][0]],
                  test_set_original[1][false_samples_lst[i][0]])

        idx_f += 1


def ae_main(input_files_dict, epochs=2, out_dir='./log', show_flg=True, **kwargs):
    """

    :param input_files_dict:
    :param epochs:
    :param out_dir:
    :return:
    """
    torch.manual_seed(1)
    start_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    st = time.time()
    print('It starts at ', start_time)

    # step 1 load input_data and do preprocessing
    train_set_without_abnormal_data, val_set_without_abnormal_data, test_set_without_abnormal_data, u_normal, std_normal = split_normal2train_val_test_from_files(
        input_files_dict['normal_files'], norm_flg=True, train_val_test_percent=[0.8, 0.2, 0.0], shuffle_flg=False)
    print('train_set:%s,val_set:%s,test_set:%s' % (
        Counter(train_set_without_abnormal_data[1]), Counter(val_set_without_abnormal_data[1]),
        Counter(test_set_without_abnormal_data[1])))
    # step 2.1 model initialization
    AE_model = AutoEncoder(in_dim=train_set_without_abnormal_data[0].shape[1],
                           epochs=epochs, show_flg=show_flg)  # train_set (no_label and no abnormal traffic)

    # step 2.2 train model
    print('\nTraining begins ...')
    AE_model.train(train_set_without_abnormal_data, val_set_without_abnormal_data)
    # AE_model.train(val_set_without_abnormal_data, train_set_without_abnormal_data)

    print('Train finished.')

    # step 3.1 dump model
    model_file = save_model(AE_model, os.path.join(out_dir, 'autoencoder_model.pth'))

    # step 3.2 load model
    AE_model = torch.load(model_file)

    # step 4 evaluate model
    # # re-evaluation on val_set to choose the best threshold.
    # max_acc_thres = evaluate_model(AE_model, val_set_without_abnormal_data, iters=100,
    #                                fig_params={'x_label': 'evluation times', 'y_label': 'accuracy on val set',
    #                                            'fig_label': 'acc',
    #                                            'title': 'accuracy on val set with different thresholds.'})
    # AE_model.T = torch.Tensor([max_acc_thres[1]])  #
    # print('the best result on val_set is ', max_acc_thres)
    print('\nEvaluating ...', end='')
    print('evaluate on train set')
    evaluate_model(AE_model, train_set_without_abnormal_data, iters=1)
    print('evaluate on val set')
    evaluate_model(AE_model, val_set_without_abnormal_data, iters=1)
    print('\n\nevaluate on test set')
    test_set_without_abnormal_data = (val_set_without_abnormal_data[0][0:2], val_set_without_abnormal_data[1][0:2])
    evaluate_model_new(AE_model, test_set_without_abnormal_data, u_normal, std_normal,
                       test_files_lst=input_files_dict['attack_files'][:2],
                       label='0')  # only evaluate on another normal data
    evaluate_model_new(AE_model, test_set_without_abnormal_data, u_normal, std_normal,
                       test_files_lst=input_files_dict['attack_files'][2:],
                       label='1')  # only evaluate on attack data
    print('Evaluation finished.')

    end_time = time.strftime('%Y-%h-%d %H:%M:%S', time.localtime())
    print('\nIt ends at ', end_time)
    print('All takes %.4f s' % (time.time() - st))


def parse_params():
    parser = argparse.ArgumentParser(prog='AE_Case4')
    parser.add_argument('-i', '--input_files_dict', type=str, dest='input_files_dict',
                        help='{\'normal_files\': [normal_file,...], \'attack_files\': [attack_file_1, attack_file_2,...]}',
                        default='../input_data/normal_demo.txt',
                        required=True)  # '-i' short name, '--input_dir' full name
    parser.add_argument('-e', '--epochs', dest='epochs', help="num of epochs", default=10)
    parser.add_argument('-o', '--out_dir', dest='out_dir', help="the output information of this scripts",
                        default='../log')
    args = vars(parser.parse_args())

    return args


if __name__ == '__main__':
    # input_files_dict={'normal_files': ['../input_data/sess_normal_0.txt'], 'attack_files': ['../input_data/sess_TDL4_HTTP_Requests_0.txt', '../input_data/sess_Rcv_Wnd_Size_0_0.txt']}
    args = parse_params()
    input_files_dict = eval(args['input_files_dict'])
    epochs = eval(args['epochs'])
    out_dir = args['out_dir']
    print('args:%s\n' % args)
    ae_main(input_files_dict, epochs, out_dir='../log')
