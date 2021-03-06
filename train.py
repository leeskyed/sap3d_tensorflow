# coding = utf-8
import tensorflow as tf
import sys
import os

import cv2, math, time, argparse, numpy as np, matplotlib, datetime
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from tensorpack.dataflow import *
from tensorpack.dataflow.imgaug import *
from dataflow import VideoDataset, ImageFromFile, mapf
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
    parser.add_argument('--validiter', type=int, default=160000, help='training mini batch')
    parser.add_argument('--saveiter', type=int, default=4000, help='training mini batch')
    parser.add_argument('--pretrain', type=str, default=None, help='finetune using SGD')

    parser.add_argument('--trainingprops',type=float, default=0.99, help='')
    parser.add_argument('--epoch', type=int, default=4, help='')
    parser.add_argument('--dataset',type=str, default='svsdndhf1k', help='svsd/dhf1k.')
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

def mkDir(dirpath):
    if os.path.exists(dirpath)==0:
        os.mkdir(dirpath)

def output_message(args, saved_dir):
    print "##########################################"
    print "  Output the Training Config  "
    print "##########################################"
    print "Structure             : ", args.structure
    print "Training dataset      : ", args.dataset
    print "Valid Iter            : ", args.validiter
    print "Save Iter             : ", args.saveiter
    print "Batch Size            : ", args.batch
    print "Input Tensor          :  (%d, %d, %d, %d, 3)" % (args.batch, args.videolength, args.imagesize[0], args.imagesize[1])
    print "Initial Learning Rate : ", args.lr
    print "Training Example Prop : ", args.trainingprops
    print ""
    print "GPU                   : ", args.gpu
    print "Info                  : ", args.info
    print "Saved Dir             : ", saved_dir
    print ""
    print "##########################################"

print "Parsing arguments..."
args = get_arguments()

os.environ["CUDA_VISIBLE_DEVICES"] = args.gpu
print ("Loading data...")
dataset = args.dataset
if dataset=='svsd':
    frame_path = ['/data/lishikai/svsd/train/left_view_svsd/']
    density_path = ['/data/lishikai/svsd/train/left_density_svsd/']
    # fixation_path = '/data/lishikai/svsd/test/left_fixation_svsd/'
elif dataset == 'dhf1k':
    frame_path = ['/data/SaliencyDataset/Video/DHF1K/frames/']
    density_path = ['/data/SaliencyDataset/Video/DHF1K/density/']
elif dataset == 'svsdndhf1k':
    frame_path = [
        '/data/lishikai/svsd/train/left_view_svsd/', 
        '/data/SaliencyDataset/Video/DHF1K/frames/'
        ]
    density_path = [
            '/data/lishikai/svsd/train/left_density_svsd/',
            '/data/SaliencyDataset/Video/DHF1K/density/'
        ]
    

# train_frame_basedir = '../svsd/test/left_view_svsd'
# train_density_basedir = '../svsd/test/view_svsd_density/'
videodataset = VideoDataset(frame_path,density_path, video_length=16, img_size=(112,112), bgr_mean_list=[98,102,90], sort='rgb')
videodataset.setup_video_dataset_p3d(overlap=args.overlap, training_example_props=0.9)
videodataset.get_frame_p3d_tf()
df = ImageFromFile(videodataset.final_train_list)
df = MultiThreadMapData(
    df, nr_thread=32,
    map_func=mapf,
    buffer_size=1000,
    strict=True)
df = BatchData(df, args.batch, remainder=False, use_list=True)
df = PrefetchDataZMQ(df, nr_proc=1)
df = RepeatedData(df, args.epoch)
df.reset_state()

# valid
gt_df = ImageFromFile(videodataset.final_valid_list)
gt_df = MultiThreadMapData(
    gt_df, nr_thread=32,
    map_func=mapf,
    buffer_size=1000,
    strict=True)
gt_df = BatchData(gt_df, args.batch, remainder=False, use_list=True)
gt_df = PrefetchDataZMQ(gt_df, nr_proc=1)
gt_df.reset_state()

print "Using dataflow to load data... It may cost a little time to create the file lists.."
structure = args.structure
validation_iter=args.validiter
plot_iter = args.plotiter
save_iter = args.saveiter
t = datetime.datetime.now().isoformat()[:-16]
dir_name = dataset+'_'+structure + '_' + str(args.batch) + '_' + str(args.lr) + '_' + args.info +'_'+ t + '/'
model_save_dir = './model/' + dir_name
logs_dir = './logs/' + dir_name
mkDir(logs_dir)
mkDir(model_save_dir)

output_message(args, model_save_dir)


def train():
    batch_size = args.batch  # train images=batch_size*frames
    sa = args.SA
    frames = 16  # 3 frames
    Dataset='svsd'
    with tf.device('/cpu:0'):
        with tf.name_scope('inputs'):
            x = tf.placeholder(tf.float32, [batch_size, frames, CROP_SIZE, CROP_SIZE, 3])
            y = tf.placeholder(tf.float32, [batch_size, 16, CROP_SIZE, CROP_SIZE])
            training = tf.placeholder(tf.bool)
            dropout = tf.placeholder(tf.float32)
    
    
    if structure == 'unet':
        pred=p3d.p3d_unet(x, dropout, batch_size, training)
    elif structure == 'concat': 
        pred=p3d.p3d_concat(x, dropout, batch_size, training)
    elif structure == 'unet++':
        pred=p3d.p3d_unetplusplus(x, dropout, batch_size, training, sa)

    pred_reshape = tf.reshape(pred, [batch_size, 16, CROP_SIZE, CROP_SIZE])

    with tf.name_scope('loss'):
        loss1 = smooth_l1_loss(pred_reshape, y, 1, 1, sigma=1.0)
        # loss1 = tf.reduce_mean(tf.reduce_sum(tf.abs(pred_reshape-y)))
        # wd_loss = tf.reduce_mean(tf.get_collection('weightdecay_losses'))
        loss = loss1 # +wd_loss
        # tf.summary.scalar('wd_loss', wd_loss)
        tf.summary.scalar('total_loss', loss)

    with tf.name_scope('train'):
        lr = args.lr
        optimizer = tf.train.AdamOptimizer(lr).minimize(loss)
        #when using BN,this dependecy must be built.
        update_ops = tf.get_collection(tf.GraphKeys.UPDATE_OPS) 
        with tf.control_dependencies(update_ops):
            train_op=tf.group(optimizer)
            

    with tf.Session(config=config) as sess:
        merged = tf.summary.merge_all()
        writer = tf.summary.FileWriter(logs_dir, sess.graph)
        init = tf.global_variables_initializer()
    
        var_list = tf.trainable_variables()
        g_list = tf.global_variables()
        bn_moving_vars = [g for g in g_list if 'moving_mean' in g.name]
        bn_moving_vars += [g for g in g_list if 'moving_variance' in g.name]
        var_list += bn_moving_vars
        saver = tf.train.Saver(var_list=var_list, max_to_keep=10)

        # load pretrain
        # rgb_variable_map = {}
        # for variable in tf.global_variables():
        #     print variable.name
        # exit()
        # if variable.name.split('/')[0] == 'RGB' and 'Adadelta' not in variable.name.split('/')[-1] \
        #     and variable.name.split('/')[2] != 'Upsampling' \
        #     and 'deconv' not in variable.name.split('/')[2] :
        #     # and 'Mixed_4' not in variable.name.split('/')[2]:
        #     # delete high-level features
        #     rgb_variable_map[variable.name.replace(':0', '')] = variable
        # rgb_saver = tf.train.Saver(var_list=rgb_variable_map, reshape=True)

        print 'Init variable'
        sess.run(init)

        # fine-tuning
        if args.pretrain:
            print args.pretrain, "Using this model to retrain..."
            ckpt = tf.train.get_checkpoint_state('./model/'+args.pretrain+'/')
            if ckpt and ckpt.model_checkpoint_path:
                print("loading checkpoint %s,waiting......" % ckpt.model_checkpoint_path)
                saver.restore(sess, ckpt.model_checkpoint_path)
                print("load complete!")

        print 'Start training'
        step = 0
        for data in df:
            step = step + 1
            train_batch_xs, train_batch_ys = data
            _, train_loss = sess.run([train_op, loss],
                     feed_dict={x: train_batch_xs, y: train_batch_ys, dropout: 0.5, training: True})
            if step<10 or step % 1000 == 0:
                result = sess.run(merged,
                                  feed_dict={x: train_batch_xs, y: train_batch_ys,
                                             dropout: 0.5, training: True})
                writer.add_summary(result, step)
                # validation
                image = sess.run(pred,
                                feed_dict={ x: train_batch_xs, dropout: 0, training: False})
                image1 = np.reshape(image, [-1, 16, CROP_SIZE, CROP_SIZE]) 
                save_image1 = np.zeros([CROP_SIZE, CROP_SIZE])
                save_image2 = np.zeros([CROP_SIZE, CROP_SIZE])
                save_image1[:, :] = image1[0, -1, :, :]*255.
                save_image2 = train_batch_ys[0][-1]*255.
                final_save_image1 = save_image1
                final_save_image2 = save_image2
                smap_save_path = os.path.join(logs_dir, 'smap_Result')
                mkDir(smap_save_path)
                smap_save_name = smap_save_path + '/' +  'step_' + str(step) + '_pred.jpg'
                cv2.imwrite(smap_save_name, final_save_image1)
                smap_save_name2 = smap_save_path + '/' +  'step_' + str(step) + '_gt.jpg'
                cv2.imwrite(smap_save_name2, final_save_image2)
    
                print 'Datetime', datetime.datetime.now().isoformat()[:-7],'Training step:', step, np.sum(final_save_image1), np.sum(final_save_image2), 'Training Loss', train_loss

            if step % validation_iter==0:
                print "Doing validation..."
                tmp_cc = []; tmp_sim = []; tmp_auc = []
                index = 0
                for valid_data in gt_df:
                    valid_batch_xs, valid_batch_ys = valid_data
                    index += 1
                    image0 = sess.run(pred, feed_dict={ x: valid_batch_xs, dropout: 0, training: False})
                    image0 = np.reshape(image0, [-1, 16, CROP_SIZE, CROP_SIZE])
                    for (prediction, ground_truth) in zip(image0, valid_batch_ys):
                        # 16 112 112 ,  16, 112, 112
                        prediction = np.array(prediction[-1])
                        ground_truth = np.array(ground_truth[-1])
                        if index % 1000 == 0:
                            print datetime.datetime.now(), ' Index', index, 'pred:', np.sum(prediction), 'gt:', np.sum(ground_truth), 'loss:', np.sum(np.abs(prediction-ground_truth))
                        tmp_cc.append(CC(prediction, ground_truth))
                        tmp_sim.append(SIM(prediction, ground_truth))
                        tmp_auc.append(AUC_Judd(prediction, ground_truth))  
                tmp_cc = np.array(tmp_cc)[~np.isnan(tmp_cc)]
                tmp_sim = np.array(tmp_sim)[~np.isnan(tmp_sim)]
                tmp_auc = np.array(tmp_auc)[~np.isnan(tmp_auc)]
                print datetime.datetime.now().isoformat()[:-7], " Step:", step, " Metrics:", np.mean(tmp_cc), np.mean(tmp_sim), np.mean(tmp_auc)

            if step % save_iter == 0:
                saver.save(sess, os.path.join(model_save_dir, 'p3d_' + str(step) + '.ckpt'))
        print 'Training Finished!'

if __name__ == "__main__":
    train()