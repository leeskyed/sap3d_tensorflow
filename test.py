# coding = utf-8
import tensorflow as tf
import sys
import os

import cv2, math, time, argparse, numpy as np, matplotlib
from datetime import datetime
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from tensorpack.dataflow import *
from tensorpack.dataflow.imgaug import *
from dataflow import VideoDataset, ImageFromFile, mapf, mapf_test
from utils.network import *
from utils.metrics import CC, SIM, AUC_Judd, KLdiv, NSS, AUC_Borji

import p3d

config = tf.ConfigProto()
config.gpu_options.allow_growth = True
CROP_SIZE = 112

def get_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument('--structure', type=str, default='unet', help="unet/concat")
    parser.add_argument('--plotiter', type=int, default=1000, help='training mini batch')
    parser.add_argument('--validiter', type=int, default=12000, help='training mini batch')
    parser.add_argument('--saveiter', type=int, default=4000, help='training mini batch')
    parser.add_argument('--pretrain', type=str, default=None, help='finetune using SGD')

    parser.add_argument('--trainingprops',type=float, default=0.9, help='')
    parser.add_argument('--dataset',type=str, default='svsd', help='svsd/dhf1k.')
    parser.add_argument('--videolength',type=int,default=16, help='16 in this network')
    parser.add_argument('--overlap',type=int,default=15, help='0 to videolength')
    parser.add_argument('--imagesize', type=tuple, default=(112,112))

    
    parser.add_argument('--normalization',type=str,default='BN', help='Using BatchNormalization or Group Normalization (BN/GN)')
    parser.add_argument('--SA',type=bool,default=True, help='Using self-attention mechanism or not (True/False)')
    parser.add_argument('--batch',type=int,default=2, help='length of video')
    parser.add_argument('--lr', type=float, default=1e-4)
    parser.add_argument('--gpu', type=str, default="0")
    
    
    parser.add_argument('--info', type=str, default='', help="add extra model information")
    return parser.parse_args()

def generate_saliency(pred_patch_smap):
    boxsize=112
    patches=pred_patch_smap.shape[0]

    pa1 = int(math.ceil(1080 / boxsize)+1)
    pa2 = int(math.ceil(1920 / boxsize)+1)
    final_smap=np.zeros([1080,1920])
    temp_smap=np.zeros([pa1*boxsize,pa2*boxsize])

    patch_no=0
    for i in range(pa1):
        for j in range(pa2):
            temp_patch=pred_patch_smap[patch_no, :, :]
            temp_smap[boxsize*i:boxsize*(i+1), boxsize*j:boxsize*(j+1)]=temp_patch
            final_smap[:,:]=temp_smap[0:1080, 0:1920]
            patch_no=patch_no+1
    return final_smap

def mkDir(dirpath):
    if os.path.exists(dirpath)==0:
        os.mkdir(dirpath)

args = get_arguments()

os.environ["CUDA_VISIBLE_DEVICES"] = args.gpu
dataset = args.dataset
if dataset=='svsd':
    frame_path = ['/data/lishikai/svsd/test/left_view_svsd/']
    density_path = ['/data/lishikai/svsd/test/left_density_svsd/']
    fixation_path = '/data/lishikai/svsd/test/left_fixation_svsd/'
    
batch_size=args.batch
videodataset = VideoDataset(frame_path,density_path, fixation_dir=fixation_path, video_length=16, img_size=(112,112), bgr_mean_list=[98,102,90], sort='rgb')
videodataset.setup_video_dataset_p3d(overlap=args.overlap, training_example_props=0)
videodataset.get_frame_p3d_tf()
# valid
gt_df = ImageFromFile(videodataset.final_valid_list)
gt_df = MultiThreadMapData(
    gt_df, nr_thread=16,
    map_func=mapf_test,
    buffer_size=500,
    strict=True)
gt_df = BatchData(gt_df, batch_size, remainder=False, use_list=True)
gt_df = PrefetchDataZMQ(gt_df, nr_proc=1)
gt_df.reset_state()

print "Using dataflow to load data... It may cost a little time to create the file lists.."
structure = args.structure


frames = 16
with tf.device('/cpu:0'):
    with tf.name_scope('inputs'):
        x = tf.placeholder(tf.float32, [batch_size, frames, CROP_SIZE, CROP_SIZE, 3])
        training = tf.placeholder(tf.bool)
        dropout = tf.placeholder(tf.float32)



modelList=[
    # 'unet_2_0.0001__2019-04-20',
    # 'concate_2_0.0001__2019-04-20',
    # 'unet++_2_0.0001__2019-04-20'
    # 'svsd_unet++_2_0.0001_TRUEsigmoid_bn_2019-04-20'
    # 'dhf1k_unet++_2_0.0001_sigmoid_gn_ol8_2019-04-21',
    # 'dhf1k_unet++_2_0.0001_sigmoid_bn_ol8_2019-04-21',
    # 'svsd_unet++_2_0.0001_sigmoid_bn_ol8_finetune_2019-04-21'
    # 'svsd_unet++_2_0.00001_sigmoid_bn_ol8_finetune_2019-04-21'
    # 'dhf1k_unet++_2_0.01_sigmoid_gn_ol8_2019-04-21',
    # 'dhf1k_unet++_2_1e-05_sigmoid_bn_ol8_2019-04-21',
    # 'svsd_unet++_2_0.0001_sigmoid_bn_ol8_finetune_2_2019-04-21',
    # 'svsd_unet++_2_0.0001_SA_sigmoid_bn_ol8_finetune_2019-04-22',
    # 'nonsa_unet++',
    # 'svsdndhf1k_unet++_2_0.0001_sigmoid_2019-04-23'
    # 'svsdndhf1k_unet++_2_0.0001_sigmoid_subsampleSA_ol8_2019-04-23'
    # 'svsdndhf1k_unet++_2_0.0001_sigmoid_subsampleSA_ol15_2019-04-24'
    # 'selected/svsdndhf1k_unet++_2_0.0001_real_downsample_ol8_2019-04-24'
    # 'svsdndhf1k_unet++_2_0.0001_real_downsample_ol8_2019-04-24'
    # 'svsdndhf1k_unet++_2_0.0001_fake_downsample_ol8_2019-04-25'
    'svsdndhf1k_unet++_2_0.0001_real_subsample_SA_ol15_2019-04-27'
]

for modelNumber in range(len(modelList)):
    structure = modelList[modelNumber].split('_')[1]
    if structure == 'unet':
        pred=p3d.p3d_unet(x, dropout, batch_size, training)
    elif structure == 'concat': 
        pred=p3d.p3d_concat(x, dropout, batch_size, training)
    elif structure == 'unet++':
        pred=p3d.p3d_unetplusplus(x, dropout, batch_size, training)
    print "Now using model", modelList[modelNumber], "with structure", structure
    with tf.Session(config=config) as sess:
        init = tf.global_variables_initializer()
        var_list = tf.trainable_variables()
        g_list = tf.global_variables()
        bn_moving_vars = [g for g in g_list if 'moving_mean' in g.name]
        bn_moving_vars += [g for g in g_list if 'moving_variance' in g.name]
        var_list += bn_moving_vars
        saver = tf.train.Saver(var_list=var_list)
        print 'Init variable'
        sess.run(init)
        # saver.restore(sess, './log/' + "model_savemodel.cpkt-" + str(111000))
        # sess.run(tf.global_variables_initializer())
        ckpt = tf.train.get_checkpoint_state("./model/"+modelList[modelNumber]+'/')
        if ckpt and ckpt.model_checkpoint_path:
            print("loading checkpoint %s,waiting......" % ckpt.model_checkpoint_path)
            saver.restore(sess, ckpt.model_checkpoint_path)
            print("load complete!")
        tmp_cc = []; tmp_sim = []; tmp_auc = []; tmp_nss = []; tmp_aucborji = [];
        index = 0
        for valid_data in gt_df:
            xs, densitys, fixations = valid_data
            index += 1
            image = sess.run(pred, feed_dict={ x: xs, dropout: 0,  training: False})
            if index % 100 == 0:
                print " Step: %d, Metrics: CC: %.3f  SIM: %.3f   NSS: %.3f  AUC_Judd: %.3f   AUC_Borji: %.3f" \
                    % (index, np.mean(tmp_cc), np.mean(tmp_sim),  np.mean(tmp_nss), np.mean(tmp_auc), np.mean(tmp_aucborji))
            image = np.reshape(image, [-1, 16, CROP_SIZE, CROP_SIZE])
            for (prediction, density, fixation) in zip(image, densitys, fixations):
                # 16 112 112 ,  16, 112, 112
                prediction = np.array(prediction[-1])
                prediction = cv2.resize(prediction,(960,1080))
                density = np.array(density[-1])
                fixation = np.array(fixation[-1])
                # print np.shape(prediction), np.shape(density), np.shape(fixation)
                tmp_cc.append(CC(prediction, density))
                tmp_sim.append(SIM(prediction, density))
                tmp_auc.append(AUC_Judd(prediction, fixation))  
                tmp_aucborji.append(AUC_Borji(prediction, fixation))
                tmp_nss.append(NSS(prediction, fixation))
        tmp_cc = np.array(tmp_cc)[~np.isnan(tmp_cc)]
        tmp_sim = np.array(tmp_sim)[~np.isnan(tmp_sim)]
        tmp_auc = np.array(tmp_auc)[~np.isnan(tmp_auc)]
        tmp_nss = np.array(tmp_nss)[~np.isnan(tmp_nss)]
        tmp_aucborji = np.array(tmp_aucborji)[~np.isnan(tmp_aucborji)]
        print " All: %d, Metrics: CC: %.3f  SIM: %.3f   NSS: %.3f  AUC_Judd: %.3f   AUC_Borji: %.3f" \
            % (index, np.mean(tmp_cc), np.mean(tmp_sim),  np.mean(tmp_nss), np.mean(tmp_auc), np.mean(tmp_aucborji))
        
    # tf.reset_default_graph()

print 'Testing Finished!'


